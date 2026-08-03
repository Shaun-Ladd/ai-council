"""The `ai-council` command-line interface."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .adapters import create_adapter
from .config import CouncilConfig, load_config
from .models import SessionState
from .models import SessionOutcome
from .orchestrator import Orchestrator
from .registry import FindingsRegistry
from .reporting import export_json, export_markdown
from .storage import SessionStore, atomic_write_json, find_session, list_sessions

app = typer.Typer(
    name="ai-council",
    help="Autonomous Claude Code / Codex / Judge collaboration framework.",
    no_args_is_help=True,
)
console = Console()

_EXIT_BY_STATE = {
    SessionState.APPROVED: 0,
    SessionState.AWAITING_HUMAN: 2,
    SessionState.BLOCKED: 3,
    SessionState.FAILED: 4,
    SessionState.CANCELLED: 5,
}


def _council_root(repo: Path) -> Path:
    return repo / ".ai-council"


def _printer(quiet: bool, verbose: bool):
    def _print(msg: str) -> None:
        if quiet:
            return
        console.print(f"[dim]{msg}[/dim]" if not verbose else msg)
    return _print


def _finish(orchestrator: Orchestrator) -> None:
    record = orchestrator.record
    state = record.state
    style = "green" if state == SessionState.APPROVED else (
        "yellow" if state == SessionState.AWAITING_HUMAN else "red"
    )
    console.print(f"\n[bold {style}]{state.value}[/bold {style}] — {record.outcome.reason}")
    console.print(f"Session: {record.id}")
    console.print(f"Report:  {orchestrator.store.final_report_md}")
    raise typer.Exit(code=_EXIT_BY_STATE.get(state, 4))


@app.command()
def discuss(
    task: Path = typer.Argument(..., exists=True, readable=True, help="Task file (e.g. TASK.md)"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Explicit config file"),
    repo: Path = typer.Option(Path("."), "--repo", help="Repository root to operate in"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Run an autonomous council discussion over TASK and produce a verdict."""
    cfg = load_config(repo_root=repo, explicit_path=config)
    orchestrator = Orchestrator.new_session(
        task, cfg, repo_root=repo, printer=_printer(quiet, verbose)
    )
    if not quiet:
        console.print(f"[bold]AI Council[/bold] session {orchestrator.record.id} started.")
    orchestrator.run()
    _finish(orchestrator)


@app.command()
def resume(
    session_id: str = typer.Argument(..., help="Session id (unique prefix accepted)"),
    config: Optional[Path] = typer.Option(None, "--config", "-c",
                                          help="Override the snapshotted config"),
    repo: Path = typer.Option(Path("."), "--repo"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Resume an interrupted session without repeating completed agent calls."""
    store = find_session(_council_root(repo), session_id)
    cfg = load_config(repo_root=repo, explicit_path=config) if config else None
    record = store.load_session()
    if record.state in (SessionState.APPROVED,):
        console.print(f"Session {record.id} is already {record.state.value}; nothing to resume.")
        raise typer.Exit(code=0)
    if record.state in (SessionState.FAILED, SessionState.BLOCKED, SessionState.CANCELLED,
                        SessionState.AWAITING_HUMAN):
        if record.state == SessionState.AWAITING_HUMAN:
            registry = FindingsRegistry.load(store.findings_json)
            pending = [f.id for f in registry.human_required()]
            if pending and not store.human_guidance_md.is_file():
                console.print(
                    f"[red]This session is waiting on human decisions for: "
                    f"{', '.join(pending)}[/red]\n"
                    "Record your decisions first, e.g.:\n"
                    f"  ai-council human {record.id} --wont-fix {pending[0]} "
                    "--note 'risk accepted'\n"
                    f"  ai-council human {record.id} --answer 'your guidance here'\n"
                    "then run resume again."
                )
                raise typer.Exit(code=2)
        # Reopen from the last non-terminal position. The invocation that led
        # to the terminal state is dropped from the checkpoint list so it is
        # re-run with fresh context (e.g. human guidance) instead of replayed.
        reopen_state = _reopen_state(record)
        console.print(
            f"Reopening {record.state.value} session at {reopen_state.value}."
        )
        record.state = reopen_state
        if record.invocations:
            dropped = record.invocations.pop()
            console.print(f"[dim]Will re-run invocation {dropped.invocation_id} with fresh context.[/dim]")
        record.churn_points = 0
        record.disagreement_counts = {}
        record.outcome = SessionOutcome()
        store.save_session(record)
    orchestrator = Orchestrator.resume_session(store, cfg, printer=_printer(quiet, verbose))
    orchestrator.run()
    _finish(orchestrator)


def _reopen_state(record) -> SessionState:
    if not record.proposals:
        return SessionState.INITIALIZING if not record.task_hash else SessionState.EXTRACTING_REQUIREMENTS
    return SessionState.ARCHITECT_REVISING


@app.command()
def human(
    session_id: str = typer.Argument(..., help="Session id (unique prefix accepted)"),
    repo: Path = typer.Option(Path("."), "--repo"),
    resolve: list[str] = typer.Option([], "--resolve", help="Finding ID to mark RESOLVED (decision made)"),
    wont_fix: list[str] = typer.Option([], "--wont-fix", help="Finding ID to accept as risk (WONT_FIX)"),
    reopen: list[str] = typer.Option([], "--reopen", help="Finding ID that MUST be fixed (back to OPEN)"),
    answer: list[str] = typer.Option([], "--answer", help="Free-text guidance for the agents (repeatable)"),
    note: str = typer.Option("", "--note", help="Rationale recorded with each finding decision"),
):
    """Record human decisions on an AWAITING_HUMAN session, then `resume` it."""
    from .models import utcnow_iso

    store = find_session(_council_root(repo), session_id)
    registry = FindingsRegistry.load(store.findings_json)
    actions: list[str] = []
    for fid in resolve:
        registry.resolve([fid], by_role="human", note=note)
        actions.append(f"{fid}: RESOLVED by human — {note or 'no note'}")
    for fid in wont_fix:
        registry.mark_wont_fix(fid, human_authorized=True, note=note)
        actions.append(f"{fid}: WONT_FIX (risk accepted by human) — {note or 'no note'}")
    for fid in reopen:
        registry.reopen([fid], by_role="human", note=note)
        actions.append(f"{fid}: reopened by human (must be fixed) — {note or 'no note'}")
    if not actions and not answer:
        console.print("Nothing to do: pass --resolve/--wont-fix/--reopen and/or --answer.")
        raise typer.Exit(code=1)
    atomic_write_json(store.findings_json, registry.dump())

    lines = [f"### Human decision — {utcnow_iso()}", ""]
    lines += [f"- {a}" for a in actions]
    lines += [f"- Guidance: {a}" for a in answer]
    with open(store.human_guidance_md, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")

    for a in actions:
        console.print(f"[green]✓[/green] {a}")
    for a in answer:
        console.print(f"[green]✓[/green] guidance recorded: {a}")
    console.print(f"\nNow continue the session with: [bold]ai-council resume {store.session_id}[/bold]")


@app.command()
def status(
    session_id: str = typer.Argument(...),
    repo: Path = typer.Option(Path("."), "--repo"),
):
    """Show the current state of a session."""
    store = find_session(_council_root(repo), session_id)
    record = store.load_session()
    table = Table(title=f"Session {record.id}", show_header=False)
    table.add_row("State", record.state.value)
    table.add_row("Outcome", record.outcome.result or "-")
    table.add_row("Reason", record.outcome.reason or "-")
    table.add_row("Task", record.task_file)
    table.add_row("Rounds", str(record.round))
    table.add_row("Judge cycles", str(record.judge_cycle))
    p = record.latest_proposal
    table.add_row("Proposal", f"v{p.version:03d} ({p.sha256[:12]}…)" if p else "-")
    table.add_row("Invocations", str(len(record.invocations)))
    console.print(table)


@app.command()
def transcript(
    session_id: str = typer.Argument(...),
    repo: Path = typer.Option(Path("."), "--repo"),
    jsonl: bool = typer.Option(False, "--jsonl", help="Print the JSONL transcript"),
):
    """Print a session's transcript."""
    store = find_session(_council_root(repo), session_id)
    path = store.transcript_jsonl if jsonl else store.transcript_md
    if not path.is_file():
        console.print("[red]No transcript recorded yet.[/red]")
        raise typer.Exit(code=1)
    print(path.read_text(encoding="utf-8"))


@app.command()
def proposal(
    session_id: str = typer.Argument(...),
    repo: Path = typer.Option(Path("."), "--repo"),
    version: Optional[int] = typer.Option(None, "--version", help="Specific version"),
):
    """Print the latest (or a specific) proposal version."""
    store = find_session(_council_root(repo), session_id)
    record = store.load_session()
    if not record.proposals:
        console.print("[red]No proposal exists yet.[/red]")
        raise typer.Exit(code=1)
    ref = record.proposals[-1] if version is None else next(
        (p for p in record.proposals if p.version == version), None
    )
    if ref is None:
        console.print(f"[red]No proposal v{version}.[/red]")
        raise typer.Exit(code=1)
    console.print(f"[dim]proposal v{ref.version:03d} sha256 {ref.sha256}[/dim]\n")
    print(Path(ref.path).read_text(encoding="utf-8"))


@app.command()
def judgment(
    session_id: str = typer.Argument(...),
    repo: Path = typer.Option(Path("."), "--repo"),
):
    """Print the latest Judge report."""
    store = find_session(_council_root(repo), session_id)
    files = sorted(store.judgments_dir.glob("*.md")) if store.judgments_dir.is_dir() else []
    if not files:
        console.print("[red]No judgment recorded yet.[/red]")
        raise typer.Exit(code=1)
    print(files[-1].read_text(encoding="utf-8"))


@app.command()
def export(
    session_id: str = typer.Argument(...),
    format: str = typer.Option("markdown", "--format", "-f", help="markdown | json"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write to file"),
    repo: Path = typer.Option(Path("."), "--repo"),
):
    """Export a session as a single markdown or JSON document."""
    store = find_session(_council_root(repo), session_id)
    if format == "markdown":
        content = export_markdown(store)
    elif format == "json":
        content = export_json(store)
    else:
        console.print(f"[red]Unknown format: {format} (expected markdown or json)[/red]")
        raise typer.Exit(code=1)
    if output:
        output.write_text(content, encoding="utf-8")
        console.print(f"Wrote {output}")
    else:
        print(content)


@app.command("list")
def list_cmd(repo: Path = typer.Option(Path("."), "--repo")):
    """List sessions in this repository."""
    sessions = list_sessions(_council_root(repo))
    if not sessions:
        console.print("No sessions found.")
        return
    table = Table("Session", "State", "Outcome", "Rounds", "Judge cycles")
    for sid in sessions:
        record = SessionStore(_council_root(repo), sid).load_session()
        table.add_row(
            sid, record.state.value, record.outcome.result or "-",
            str(record.round), str(record.judge_cycle),
        )
    console.print(table)


@app.command("validate-config")
def validate_config(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    repo: Path = typer.Option(Path("."), "--repo"),
):
    """Validate the effective configuration and print it."""
    try:
        cfg = load_config(repo_root=repo, explicit_path=config)
    except Exception as exc:
        console.print(f"[red]Configuration invalid:[/red] {exc}")
        raise typer.Exit(code=1)
    console.print("[green]Configuration valid.[/green]")
    console.print_json(json.dumps(cfg.model_dump(mode="json")))


@app.command()
def doctor(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    repo: Path = typer.Option(Path("."), "--repo"),
):
    """Check that configured agent CLIs are available."""
    cfg = load_config(repo_root=repo, explicit_path=config)
    ok = True
    for role in ("architect", "reviewer", "judge"):
        agent_cfg = getattr(cfg.agents, role)
        try:
            adapter = create_adapter(agent_cfg, cfg.security)
            available, detail = adapter.doctor()
        except Exception as exc:
            available, detail = False, str(exc)
            adapter = None
        style = "green" if available else "red"
        name = adapter.name if adapter else agent_cfg.adapter
        console.print(f"[{style}]{'OK ' if available else 'FAIL'}[/{style}] {role} ({name}): {detail}")
        ok = ok and available
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def version():
    """Print the ai-council version."""
    console.print(f"ai-council {__version__}")


if __name__ == "__main__":
    app()
