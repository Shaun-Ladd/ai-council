"""Final reports: final-plan.md, final-report.md, final-report.json,
unresolved.md, plus transcript/status exports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .evidence import EvidenceStore
from .models import (
    JudgeStatus,
    RequirementsDoc,
    SessionRecord,
    SessionState,
)
from .registry import FindingsRegistry
from .storage import SessionStore, atomic_write_json, atomic_write_text


def write_reports(
    *,
    store: SessionStore,
    record: SessionRecord,
    registry: FindingsRegistry,
    requirements: Optional[RequirementsDoc],
    last_judge: Optional[JudgeStatus],
    evidence: Optional[EvidenceStore] = None,
) -> None:
    proposal = record.latest_proposal
    open_findings = registry.open_findings()

    # ---- final-report.json ------------------------------------------------
    report = {
        "session_id": record.id,
        "task_file": record.task_file,
        "task_hash": record.task_hash,
        "outcome": record.outcome.result,
        "reason": record.outcome.reason,
        "state": record.state.value,
        "approved_by_judge": record.state == SessionState.APPROVED,
        "rounds": record.round,
        "judge_cycles": record.judge_cycle,
        "proposal": (
            {"version": proposal.version, "sha256": proposal.sha256, "path": proposal.path}
            if proposal else None
        ),
        "open_findings": [f.model_dump(mode="json") for f in open_findings],
        "all_findings_count": len(registry.findings),
        "requirement_verdicts": (
            [v.model_dump(mode="json") for v in last_judge.requirement_verdicts]
            if last_judge else []
        ),
        "evidence": (
            [i.model_dump(mode="json") for i in evidence.items] if evidence else []
        ),
        "invocations": len(record.invocations),
    }
    atomic_write_json(store.final_report_json, report)

    # ---- final-report.md --------------------------------------------------
    lines = [
        f"# AI Council Final Report — session {record.id}",
        "",
        f"- Task: `{record.task_file}` (sha256 {record.task_hash[:12]}…)",
        f"- Outcome: **{record.outcome.result or record.state.value}**",
        f"- Reason: {record.outcome.reason}",
        f"- Debate rounds: {record.round}; Judge cycles: {record.judge_cycle}",
    ]
    if proposal:
        lines.append(
            f"- Final proposal: v{proposal.version:03d} (sha256 `{proposal.sha256}`)"
        )
    lines.append("")

    if record.state == SessionState.APPROVED:
        lines += [
            "## Approval",
            "",
            f"**Approved by Judge.** {record.outcome.reason}",
        ]
        if last_judge and last_judge.approval_statement:
            lines += ["", f"> {last_judge.approval_statement}"]
    elif record.state == SessionState.AWAITING_HUMAN:
        lines += [
            "## Human intervention required",
            "",
            record.outcome.reason,
            "",
            "### What the council needs from you",
        ]
        questions = []
        if last_judge:
            questions += last_judge.human_questions
        lines += [f"- {q}" for q in questions] or ["- See the findings awaiting your decision below."]
        pending = registry.human_required()
        if pending:
            lines += ["", "### Findings awaiting your decision", ""]
            for f in pending:
                lines.append(f"- **{f.id}** [{f.severity.value}] {f.title}")
                history = [h for h in f.history if "HUMAN_REQUIRED" in h]
                if history:
                    lines.append(f"  - architect: {history[-1].split('HUMAN_REQUIRED: ', 1)[-1]}")
        example = pending[0].id if pending else "RVW-001"
        lines += [
            "",
            "### How to respond",
            "",
            "Record your decisions, then resume — the council continues with",
            "your guidance treated as authoritative:",
            "",
            f"    ai-council human {record.id} --wont-fix {example} --note 'risk accepted'",
            f"    ai-council human {record.id} --resolve {example} --note 'decided: ...'",
            f"    ai-council human {record.id} --reopen {example} --note 'must be fixed'",
            f"    ai-council human {record.id} --answer 'free-text guidance for the agents'",
            f"    ai-council resume {record.id}",
        ]
    elif record.state in (SessionState.FAILED, SessionState.BLOCKED, SessionState.CANCELLED):
        lines += [
            f"## {record.state.value.title()} report",
            "",
            record.outcome.reason,
            "",
            "### Recovery",
            "",
            f"- Inspect the transcript: `ai-council transcript {record.id}`",
            f"- Inspect session state: `ai-council status {record.id}`",
            f"- Resume (repeats no completed agent calls): `ai-council resume {record.id}`",
            "- If limits were reached, raise `session.maxDebateRounds` / "
            "`session.maxJudgeCycles` in the config and resume, or start a new "
            "session with a clarified task.",
        ]

    if open_findings:
        lines += ["", "## Open findings", "", registry.to_markdown(only_open=True)]
    if requirements is not None and last_judge is not None:
        lines += ["", "## Requirement verdicts (Judge)", ""]
        verdicts = {v.requirement_id: v for v in last_judge.requirement_verdicts}
        for req in requirements.requirements:
            v = verdicts.get(req.id)
            lines.append(
                f"- {req.id}: {v.verdict if v else 'NOT EVALUATED'}"
                + (f" — {v.notes}" if v and v.notes else "")
            )
    atomic_write_text(store.final_report_md, "\n".join(lines) + "\n")

    # ---- final-plan.md (approved sessions only) ---------------------------
    if record.state == SessionState.APPROVED and proposal:
        plan_header = (
            f"# Final Plan — session {record.id}\n\n"
            f"Approved by Judge: proposal v{proposal.version:03d} "
            f"(sha256 `{proposal.sha256}`).\n\n---\n\n"
        )
        atomic_write_text(
            store.final_plan_md,
            plan_header + Path(proposal.path).read_text(encoding="utf-8"),
        )

    # ---- unresolved.md ----------------------------------------------------
    atomic_write_text(
        store.unresolved_md,
        f"# Unresolved items — session {record.id}\n\n"
        + registry.to_markdown(only_open=True)
        + "\n",
    )

    # ---- refresh convenience copies at the .ai-council/ root --------------
    latest_review = _latest(store.reviews_dir)
    latest_judgment = _latest(store.judgments_dir)
    store.refresh_root_copies(
        latest_proposal=Path(proposal.path) if proposal else None,
        latest_review=latest_review,
        latest_judgment=latest_judgment,
    )


def _latest(directory: Path) -> Optional[Path]:
    if not directory.is_dir():
        return None
    files = sorted(p for p in directory.iterdir() if p.suffix == ".md")
    return files[-1] if files else None


def export_markdown(store: SessionStore) -> str:
    """Single-document export of a session: report + transcript."""
    parts = []
    for path in (store.final_report_md, store.transcript_md):
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts) if parts else "_Session has no report yet._"


def export_json(store: SessionStore) -> str:
    record = store.load_session()
    payload = {
        "session": record.model_dump(mode="json"),
        "final_report": (
            json.loads(store.final_report_json.read_text(encoding="utf-8"))
            if store.final_report_json.is_file() else None
        ),
        "findings": (
            json.loads(store.findings_json.read_text(encoding="utf-8"))
            if store.findings_json.is_file() else {"findings": []}
        ),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
