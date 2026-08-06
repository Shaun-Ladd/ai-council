"""Implementation-mode integration tests: plan debate -> worktree coding ->
diff review -> orchestrator-run tests -> implementation Judge gate."""
from __future__ import annotations

import json
import subprocess

import pytest

from ai_council.config import CouncilConfig
from ai_council.models import SessionState
from ai_council.orchestrator import Orchestrator
from ai_council.worktree import compute_diff, create_worktree, is_git_repo

from council_fixtures import (
    ALL_ADDRESSED,
    APPROVAL_STATEMENT,
    PROPOSAL_V1,
    TASK_TEXT,
    _mock,
    approve_judge,
    architect_agree_response,
    architect_proposal_response,
    extraction,
    judge_response,
    reviewer_response,
)

WIDGET_CODE = "def import_widgets(rows):\n    return [r for r in rows if r]\n"
WIDGET_CODE_V2 = WIDGET_CODE + "\n\ndef rollback(batch):\n    return True\n"
PASSING_TEST = "import widgets\nassert widgets.import_widgets([1, None]) == [1]\nprint('ok')\n"


def _git_repo(tmp_path):
    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "README.md").write_text("# target\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=repo, check=True,
    )
    return repo


def impl_config(**impl_overrides) -> CouncilConfig:
    return CouncilConfig.model_validate({
        "agents": {r: {"adapter": "mock"} for r in
                   ("architect", "reviewer", "judge", "extractor")},
        "implementation": impl_overrides,
    })


def approve_impl_judge():
    return judge_response(
        "APPROVED",
        requirement_verdicts=ALL_ADDRESSED,
        approval_statement=APPROVAL_STATEMENT,
    )


def _write_task(repo):
    task = repo / "TASK.md"
    task.write_text(TASK_TEXT)
    return task


def test_worktree_helpers(tmp_path):
    repo = _git_repo(tmp_path)
    assert is_git_repo(repo)
    path, branch = create_worktree(repo, "sess-1")
    assert path.is_dir() and branch == "ai-council/sess-1"
    (path / "widgets.py").write_text(WIDGET_CODE)
    diff = compute_diff(path)
    assert "widgets.py" in diff and "+def import_widgets" in diff
    # user's checkout untouched
    assert not (repo / "widgets.py").exists()
    # idempotent create (resume)
    path2, _ = create_worktree(repo, "sess-1")
    assert path2 == path


def test_implement_happy_path_with_tests(tmp_path):
    repo = _git_repo(tmp_path)
    task = _write_task(repo)
    cfg = impl_config(
        testCommand=f"{__import__('sys').executable} test_widgets.py",
    )
    o = Orchestrator.new_session(task, cfg, repo_root=repo, implement_mode=True)
    o._adapters = {
        "extractor": _mock([extraction()], False),
        "architect": _mock([
            architect_proposal_response(PROPOSAL_V1),      # plan
            architect_agree_response(),                    # plan confirm
            {"response": architect_proposal_response(     # implementation
                "Implemented the importer with validation and tests."),
             "write_files": {"widgets.py": WIDGET_CODE,
                             "test_widgets.py": PASSING_TEST}},
            architect_agree_response(),                    # impl confirm
        ], False),
        "reviewer": _mock([
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),   # plan
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),   # impl diff
        ], False),
        "judge": _mock([
            approve_judge(),        # plan judge
            approve_impl_judge(),   # implementation judge
        ], False),
    }
    record = o.run()
    assert record.state == SessionState.IMPLEMENTED, record.outcome.reason
    assert record.latest_implementation.version == 1
    # code exists only on the council branch/worktree
    assert (tmp_path / "target" / ".ai-council" / "worktrees" / record.id / "widgets.py").is_file()
    assert not (repo / "widgets.py").exists()
    # diff artifact is immutable and hashed
    diff_text = (o.store.impl_diff_path(1)).read_text()
    assert "+def import_widgets" in diff_text
    # orchestrator-run test evidence recorded, and it passed
    evidence = json.loads((o.store.evidence_dir / "index.json").read_text())["items"]
    tests = [i for i in evidence if i["type"] == "test"]
    assert tests and tests[-1]["exit_code"] == 0
    # report includes merge instructions
    report = o.store.final_report_md.read_text()
    assert f"git merge ai-council/{record.id}" in report
    assert o.store.final_implementation_diff.is_file()


def test_impl_review_revision_loop(tmp_path):
    repo = _git_repo(tmp_path)
    task = _write_task(repo)
    diff_finding = {
        "title": "No rollback in importer",
        "severity": "BLOCKING",
        "detail": "widgets.py lacks rollback handling.",
        "cited_section": "widgets.py",
    }
    o = Orchestrator.new_session(task, impl_config(), repo_root=repo, implement_mode=True)
    o._adapters = {
        "extractor": _mock([extraction()], False),
        "architect": _mock([
            architect_proposal_response(PROPOSAL_V1),
            architect_agree_response(),
            {"response": architect_proposal_response("Implemented importer."),
             "write_files": {"widgets.py": WIDGET_CODE}},
            {"response": architect_proposal_response(
                "Added rollback.", decision="REVISED",
                finding_responses=[{"finding_id": "RVW-001", "action": "FIXED",
                                    "response": "rollback added"}]),
             "write_files": {"widgets.py": WIDGET_CODE_V2}},
            architect_agree_response(),
        ], False),
        "reviewer": _mock([
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),          # plan
            reviewer_response("REVISE", new_findings=[diff_finding]),          # impl v1
            reviewer_response("APPROVE_FOR_JUDGE",                             # impl v2
                              resolved_finding_ids=["RVW-001"], confidence=0.95),
        ], False),
        "judge": _mock([approve_judge(), approve_impl_judge()], False),
    }
    record = o.run()
    assert record.state == SessionState.IMPLEMENTED, record.outcome.reason
    assert record.latest_implementation.version == 2
    assert record.impl_round == 2
    assert o.store.impl_diff_path(1).is_file() and o.store.impl_diff_path(2).is_file()


def test_impl_judge_approval_requires_green_tests(tmp_path):
    repo = _git_repo(tmp_path)
    task = _write_task(repo)
    cfg = impl_config(testCommand=f"{__import__('sys').executable} -c 'raise SystemExit(1)'")
    o = Orchestrator.new_session(task, cfg, repo_root=repo, implement_mode=True)
    o._adapters = {
        "extractor": _mock([extraction()], False),
        "architect": _mock([
            architect_proposal_response(PROPOSAL_V1),
            architect_agree_response(),
            {"response": architect_proposal_response("Implemented."),
             "write_files": {"widgets.py": WIDGET_CODE}},
            architect_agree_response(),
        ], False),
        "reviewer": _mock([
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
        ], False),
        # judge wrongly approves despite failing tests -> orchestrator rejects
        "judge": _mock([approve_judge(), approve_impl_judge()], False),
    }
    record = o.run()
    assert record.state == SessionState.FAILED
    assert "FAILED (exit 1)" in record.outcome.reason


def test_implement_requires_git_repo(tmp_path, task_file):
    o = Orchestrator.new_session(task_file, impl_config(), repo_root=tmp_path,
                                 implement_mode=True)
    o._adapters = {
        "extractor": _mock([extraction()], False),
        "architect": _mock([architect_proposal_response(PROPOSAL_V1),
                            architect_agree_response()], False),
        "reviewer": _mock([reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)], False),
        "judge": _mock([approve_judge()], False),
    }
    record = o.run()
    assert record.state == SessionState.FAILED
    assert "not a git repository" in record.outcome.reason


def test_impl_phase_gets_fresh_counters(tmp_path):
    """Churn/disagreement accumulated during planning must not shrink the
    implementation phase's budget."""
    repo = _git_repo(tmp_path)
    task = _write_task(repo)
    o = Orchestrator.new_session(task, impl_config(), repo_root=repo, implement_mode=True)
    o._adapters = {
        "extractor": _mock([extraction()], False),
        "architect": _mock([
            architect_proposal_response(PROPOSAL_V1),
            architect_agree_response(),
            {"response": architect_proposal_response("Implemented."),
             "write_files": {"widgets.py": WIDGET_CODE}},
            architect_agree_response(),
        ], False),
        "reviewer": _mock([
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
        ], False),
        "judge": _mock([approve_judge(), approve_impl_judge()], False),
    }
    # simulate plan-phase wear on the shared counters
    o.record.churn_points = 2
    o.record.disagreement_counts = {"sig": 1}
    record = o.run()
    assert record.state == SessionState.IMPLEMENTED
    assert record.churn_points == 0
    assert record.disagreement_counts == {}
    # independent budgets: plan rounds consumed, impl counters started fresh
    assert record.round == 1 and record.impl_round == 1
    assert record.judge_cycle == 1 and record.impl_judge_cycle == 1


def _approved_discuss_session(repo, task):
    """Run a discuss-style session to APPROVED and return its store."""
    from council_fixtures import mock_config
    o = Orchestrator.new_session(task, mock_config(), repo_root=repo)
    o._adapters = {
        "extractor": _mock([extraction()], False),
        "architect": _mock([architect_proposal_response(PROPOSAL_V1),
                            architect_agree_response()], False),
        "reviewer": _mock([reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)], False),
        "judge": _mock([approve_judge()], False),
    }
    record = o.run()
    assert record.state == SessionState.APPROVED
    return o.store, record


def test_implement_from_approved_session(tmp_path):
    repo = _git_repo(tmp_path)
    task = _write_task(repo)
    source_store, source_record = _approved_discuss_session(repo, task)
    plan = source_record.latest_proposal

    o = Orchestrator.implement_from_session(source_store, impl_config(), repo_root=repo)
    o._adapters = {
        "extractor": _mock([], False),   # must never be invoked
        "architect": _mock([
            {"response": architect_proposal_response("Implemented per seeded plan."),
             "write_files": {"widgets.py": WIDGET_CODE}},
            architect_agree_response(),
        ], False),
        "reviewer": _mock([reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)], False),
        "judge": _mock([approve_impl_judge()], False),
    }
    record = o.run()
    assert record.state == SessionState.IMPLEMENTED, record.outcome.reason
    # plan carried over with exact version and hash
    assert record.latest_proposal.version == plan.version
    assert record.latest_proposal.sha256 == plan.sha256
    # no plan-phase agent calls happened: only impl invocations exist
    purposes = {inv.purpose for inv in record.invocations}
    assert purposes == {"implement", "impl-review", "impl-confirm", "impl-judge"}
    # provenance in the decisions log
    decisions = o.store.decisions_md.read_text()
    assert f"seeded from approved session {source_record.id}" in decisions
    # requirements carried over
    assert o.store.requirements_json.is_file()


def test_implement_from_session_requires_approved(tmp_path):
    repo = _git_repo(tmp_path)
    task = _write_task(repo)
    from council_fixtures import mock_config
    o = Orchestrator.new_session(task, mock_config(), repo_root=repo)
    o._adapters = {
        "extractor": _mock([extraction()], False),
        "architect": _mock([architect_proposal_response(
            PROPOSAL_V1, decision="HUMAN_REQUIRED",
            human_questions=["which db?"])], False),
        "reviewer": _mock([], False),
        "judge": _mock([], False),
    }
    record = o.run()
    assert record.state == SessionState.AWAITING_HUMAN
    with pytest.raises(ValueError, match="only a session with a Judge-APPROVED plan"):
        Orchestrator.implement_from_session(o.store, impl_config(), repo_root=repo)


def test_implement_from_session_task_hash_mismatch(tmp_path):
    repo = _git_repo(tmp_path)
    task = _write_task(repo)
    source_store, _ = _approved_discuss_session(repo, task)
    other_task = repo / "OTHER.md"
    other_task.write_text("# A completely different task\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        Orchestrator.implement_from_session(
            source_store, impl_config(), repo_root=repo, task_path=other_task,
        )
