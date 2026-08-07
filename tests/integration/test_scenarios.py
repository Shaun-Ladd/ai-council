"""Integration tests: the full orchestrator driven by scripted mock agents.

Covers the 18 scenarios required by the task specification.
"""
from __future__ import annotations

import json

from ai_council.adapters.mock import status_response
from ai_council.models import FindingStatus, SessionState
from ai_council.orchestrator import Orchestrator
from ai_council.registry import FindingsRegistry
from ai_council.storage import SessionStore

from council_fixtures import (
    BLOCKING_FINDING,
    PROPOSAL_V1,
    PROPOSAL_V2,
    approve_judge,
    architect_agree_response,
    architect_proposal_response,
    build_orchestrator,
    judge_response,
    mock_config,
    reviewer_response,
)

PROPOSAL_V3 = PROPOSAL_V2 + "\n## Rollback\n\nImports can be rolled back by batch id.\n"


def architect_echo_response(
    decision: str,
    finding_responses: list | None = None,
    unresolved_objections: list | None = None,
    confidence: float = 0.9,
):
    """Architect defense/objection response echoing the current version+hash."""
    status = {
        "role": "architect",
        "decision": decision,
        "proposal_version": "{{PROPOSAL_VERSION}}",
        "proposal_hash": "{{PROPOSAL_HASH}}",
        "confidence": confidence,
        "summary": f"Architect responds with {decision}.",
        "material_change": False,
        "finding_responses": finding_responses or [],
        "unresolved_objections": unresolved_objections or [],
    }
    text = status_response(f"Architect {decision.lower()}s.", status)
    return text.replace('"{{PROPOSAL_VERSION}}"', "{{PROPOSAL_VERSION}}")


def run(o: Orchestrator):
    record = o.run()
    return record


# ---------------------------------------------------------------------
# 1. Claude and Codex agree; Judge approves.
# ---------------------------------------------------------------------
def test_scenario_01_agree_and_judge_approves(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[architect_proposal_response(PROPOSAL_V1), architect_agree_response()],
        reviewer=[reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    assert record.judge_cycle == 1
    assert record.latest_proposal.version == 1

    report = json.loads(o.store.final_report_json.read_text())
    assert report["approved_by_judge"] is True
    assert "Approved by Judge" in o.store.final_report_md.read_text()
    assert o.store.final_plan_md.is_file()
    # transcript preserved
    events = [json.loads(l) for l in o.store.transcript_jsonl.read_text().splitlines()]
    assert any(e["kind"] == "agent_response" and e["role"] == "judge" for e in events)


# ---------------------------------------------------------------------
# 2. Codex requests revision; Claude fixes it; Judge approves.
# ---------------------------------------------------------------------
def test_scenario_02_revision_then_approval(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_proposal_response(
                PROPOSAL_V2, decision="REVISED",
                finding_responses=[{"finding_id": "RVW-001", "action": "FIXED",
                                    "response": "Added failure handling."}],
            ),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("REVISE", new_findings=[BLOCKING_FINDING], confidence=0.9),
            reviewer_response("APPROVE_FOR_JUDGE", resolved_finding_ids=["RVW-001"],
                              confidence=0.95),
        ],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    assert record.latest_proposal.version == 2
    assert record.round == 2
    registry = FindingsRegistry.load(o.store.findings_json)
    assert registry.get("RVW-001").status == FindingStatus.RESOLVED
    # both proposal versions immutably archived
    assert o.store.proposal_path(1).is_file() and o.store.proposal_path(2).is_file()


# ---------------------------------------------------------------------
# 3. Agents agree; Judge rejects; agents revise; Judge approves.
# ---------------------------------------------------------------------
def test_scenario_03_judge_rejects_then_approves(task_file, tmp_path):
    judge_finding = {
        "title": "Missing rollback story",
        "severity": "BLOCKING",
        "detail": "No rollback for partial imports.",
        "why_it_matters": "Operational risk.",
        "acceptance_condition": "Document rollback.",
    }
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_agree_response(),
            architect_proposal_response(
                PROPOSAL_V2, decision="REVISED",
                finding_responses=[{"finding_id": "JDG-001", "action": "FIXED",
                                    "response": "Added rollback."}],
            ),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
            reviewer_response("APPROVE_FOR_JUDGE", resolved_finding_ids=["JDG-001"],
                              confidence=0.95),
        ],
        judge=[
            judge_response("REVISE", new_findings=[judge_finding],
                           requirement_verdicts=[
                               {"requirement_id": "REQ-001", "verdict": "ADDRESSED"},
                               {"requirement_id": "REQ-002", "verdict": "PARTIAL"},
                           ]),
            approve_judge(),
        ],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    assert record.judge_cycle == 2
    assert record.latest_proposal.version == 2
    # Judge can reject a candidate both agents accepted; rejection stays in audit trail
    assert o.store.judgment_path(1, 1).is_file()
    assert o.store.judgment_path(2, 2).is_file()


# ---------------------------------------------------------------------
# 4. Judge rejects repeatedly; maximum Judge cycles reached.
# ---------------------------------------------------------------------
def test_scenario_04_max_judge_cycles(task_file, tmp_path):
    finding = dict(BLOCKING_FINDING)
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(maxJudgeCycles=2),
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_agree_response(),
            architect_proposal_response(
                PROPOSAL_V2, decision="REVISED",
                finding_responses=[{"finding_id": "JDG-001", "action": "FIXED",
                                    "response": "fixed"}]),
            architect_agree_response(),
            architect_proposal_response(
                PROPOSAL_V3, decision="REVISED",
                finding_responses=[{"finding_id": "JDG-002", "action": "FIXED",
                                    "response": "fixed"}]),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
            reviewer_response("APPROVE_FOR_JUDGE", resolved_finding_ids=["JDG-001"],
                              confidence=0.95),
            reviewer_response("APPROVE_FOR_JUDGE", resolved_finding_ids=["JDG-002"],
                              confidence=0.95),
        ],
        judge=[
            judge_response("REVISE", new_findings=[finding]),
            judge_response("REVISE", new_findings=[finding]),
        ],
    )
    record = run(o)
    assert record.state == SessionState.BLOCKED
    assert "Maximum Judge cycles" in record.outcome.reason
    assert record.judge_cycle == 2


# ---------------------------------------------------------------------
# 5. An agent references an outdated proposal version.
# ---------------------------------------------------------------------
def test_scenario_05_outdated_proposal_version(task_file, tmp_path):
    stale = reviewer_response("APPROVE_FOR_JUDGE", version="99", confidence=0.95)
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(maxAgentFailures=0),
        architect=[architect_proposal_response(PROPOSAL_V1)],
        reviewer=[stale],
        judge=[],
    )
    record = run(o)
    assert record.state == SessionState.FAILED
    assert "stale proposal" in record.outcome.reason


# ---------------------------------------------------------------------
# 6. Proposal version matches but hash does not.
# ---------------------------------------------------------------------
def test_scenario_06_hash_mismatch(task_file, tmp_path):
    bad_hash = reviewer_response("APPROVE_FOR_JUDGE", hash_="f" * 64, confidence=0.95)
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(maxAgentFailures=0),
        architect=[architect_proposal_response(PROPOSAL_V1)],
        reviewer=[bad_hash],
        judge=[],
    )
    record = run(o)
    assert record.state == SessionState.FAILED
    assert "stale proposal" in record.outcome.reason


# ---------------------------------------------------------------------
# 7. Malformed JSON is repaired.
# ---------------------------------------------------------------------
def test_scenario_07_malformed_json_repaired(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[architect_proposal_response(PROPOSAL_V1), architect_agree_response()],
        reviewer=[
            "Looks good to me! (no status block)",
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
        ],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    # the format-repair retry did not consume a debate round
    assert record.round == 1
    transcript = o.store.transcript_md.read_text()
    assert "Invalid structured output" in transcript
    # invalid response preserved in raw logs
    logs = list(o.store.logs_dir.glob("review-*-a1.stdout.log"))
    assert logs and "no status block" in logs[0].read_text()


# ---------------------------------------------------------------------
# 8. Malformed JSON repeatedly fails.
# ---------------------------------------------------------------------
def test_scenario_08_malformed_json_exhausts_retries(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(maxFormatRetries=1),
        architect=[architect_proposal_response(PROPOSAL_V1)],
        reviewer=["no block 1", "no block 2"],
        judge=[],
    )
    record = run(o)
    assert record.state == SessionState.FAILED
    assert "failed validation" in record.outcome.reason


# ---------------------------------------------------------------------
# 9. An agent times out.
# ---------------------------------------------------------------------
def test_scenario_09_agent_timeout(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(maxAgentFailures=0),
        architect=[architect_proposal_response(PROPOSAL_V1)],
        reviewer=[{"behavior": "timeout"}],
        judge=[],
    )
    record = run(o)
    assert record.state == SessionState.FAILED
    assert "[TIMEOUT]" in record.outcome.reason


def test_scenario_09b_timeout_then_retry_succeeds(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(maxAgentFailures=1),
        architect=[architect_proposal_response(PROPOSAL_V1), architect_agree_response()],
        reviewer=[{"behavior": "timeout"},
                  reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED


# ---------------------------------------------------------------------
# 10. A session is interrupted and resumed.
# ---------------------------------------------------------------------
def test_scenario_10_interrupt_and_resume(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[architect_proposal_response(PROPOSAL_V1)],
        reviewer=[{"behavior": "interrupt"}],
        judge=[],
    )
    record = run(o)
    assert record.state == SessionState.CANCELLED
    session_id = record.id
    completed_before = {inv.invocation_id for inv in record.invocations}
    assert any("propose" in i for i in completed_before)

    # Reopen (as `ai-council resume` does for gracefully cancelled sessions)
    store = SessionStore(tmp_path / ".ai-council", session_id)
    reopened = store.load_session()
    reopened.state = SessionState.ARCHITECT_REVISING
    store.save_session(reopened)

    o2 = Orchestrator.resume_session(store, mock_config())
    o2._adapters = o._adapters  # fresh scripts below
    from council_fixtures import _mock
    o2._adapters = {
        "extractor": _mock([], False),
        "architect": _mock([architect_agree_response()], False),
        "reviewer": _mock([reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)], False),
        "judge": _mock([approve_judge()], False),
    }
    record2 = o2.run()
    assert record2.state == SessionState.APPROVED
    # completed calls were not repeated: extractor/propose scripts were empty,
    # and the original checkpoints are still present
    assert completed_before <= {inv.invocation_id for inv in record2.invocations}
    assert record2.latest_proposal.version == 1


# ---------------------------------------------------------------------
# 11. Human input is required.
# ---------------------------------------------------------------------
def test_scenario_11_human_required(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[architect_proposal_response(
            PROPOSAL_V1, decision="HUMAN_REQUIRED",
            human_questions=["Which database does the widget DB use?"],
        )],
        reviewer=[], judge=[],
    )
    record = run(o)
    assert record.state == SessionState.AWAITING_HUMAN
    assert "Which database" in record.outcome.reason
    report = o.store.final_report_md.read_text()
    assert "Human intervention required" in report
    assert "ai-council resume" in report


# ---------------------------------------------------------------------
# 12. A blocking finding is improperly marked resolved.
# ---------------------------------------------------------------------
def test_scenario_12_improper_resolution_rejected(task_file, tmp_path):
    judge_finding = {
        "title": "Unhandled encoding errors",
        "severity": "BLOCKING",
        "detail": "CSV encoding failures are not handled.",
    }
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(maxDebateRounds=2, repeatedDisagreementLimit=99),
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_agree_response(),
            # architect only DEFENDS the judge finding — it is not fixed
            architect_echo_response(
                "AGREED",
                finding_responses=[{"finding_id": "JDG-001", "action": "DEFENDED",
                                    "response": "Not needed."}],
                confidence=0.95,
            ),
        ],
        reviewer=[
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
            # improper: reviewer claims the unfixed judge finding is resolved
            reviewer_response("APPROVE_FOR_JUDGE", resolved_finding_ids=["JDG-001"],
                              confidence=0.95),
        ],
        judge=[judge_response("REVISE", new_findings=[judge_finding])],
        loop_last=True,
    )
    record = run(o)
    assert record.state == SessionState.BLOCKED  # rounds exhausted, finding still open
    registry = FindingsRegistry.load(o.store.findings_json)
    assert registry.get("JDG-001").status == FindingStatus.OPEN
    assert "Rejected improper resolution of JDG-001" in o.store.transcript_md.read_text()


# ---------------------------------------------------------------------
# 13. Proposal changes after reviewer approval -> new review required.
# ---------------------------------------------------------------------
def test_scenario_13_change_after_approval_requires_rereview(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            # at confirmation time the architect objects instead of agreeing
            architect_echo_response("DISAGREE",
                                    unresolved_objections=["Failure handling missing"]),
            architect_proposal_response(PROPOSAL_V2, decision="REVISED"),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
        ],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    assert record.latest_proposal.version == 2
    # v1 approval did not carry over: v2 got its own review before judgment
    assert o.store.review_path(1, 1).is_file()
    assert o.store.review_path(2, 2).is_file()
    assert o.store.judgment_path(2, 1).is_file()  # judge only ever saw v2


# ---------------------------------------------------------------------
# 14. Judge requests evidence.
# ---------------------------------------------------------------------
def test_scenario_14_judge_requests_evidence(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_agree_response(),
            architect_proposal_response(
                PROPOSAL_V2, decision="REVISED",
                finding_responses=[{"finding_id": "JDG-001", "action": "FIXED",
                                    "response": "Added idempotency test evidence plan."}],
            ),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
            reviewer_response("APPROVE_FOR_JUDGE", resolved_finding_ids=["JDG-001"],
                              confidence=0.95),
        ],
        judge=[
            judge_response("EVIDENCE_REQUIRED", evidence_requests=[
                {"description": "test results demonstrating idempotent re-import",
                 "type": "test", "related_requirement_ids": ["REQ-002"]},
            ]),
            approve_judge(),
        ],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    registry = FindingsRegistry.load(o.store.findings_json)
    finding = registry.get("JDG-001")
    assert finding.title.startswith("Evidence required:")
    assert finding.status == FindingStatus.RESOLVED


# ---------------------------------------------------------------------
# 15. Agents reach superficial consensus with an unmet requirement.
# ---------------------------------------------------------------------
def test_scenario_15_superficial_consensus_detected(task_file, tmp_path):
    incomplete = PROPOSAL_V1.replace(
        "- REQ-002: upsert keyed on widget SKU makes re-runs idempotent.\n", ""
    )
    assert "REQ-002" not in incomplete
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[
            architect_proposal_response(incomplete),
            architect_agree_response(),          # confirms despite the gap
            architect_proposal_response(PROPOSAL_V1, decision="REVISED"),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),  # superficial
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
        ],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    assert record.latest_proposal.version == 2
    decisions = o.store.decisions_md.read_text()
    assert "does not reference requirements: REQ-002" in decisions


# ---------------------------------------------------------------------
# 16. Repeated disagreement is detected.
# ---------------------------------------------------------------------
def test_scenario_16_repeated_disagreement(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(repeatedDisagreementLimit=2),
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_echo_response(
                "DISAGREE",
                finding_responses=[{"finding_id": "RVW-001", "action": "DEFENDED",
                                    "response": "By design."}],
            ),
        ],
        reviewer=[
            reviewer_response("DISAGREE", new_findings=[BLOCKING_FINDING]),
            reviewer_response("DISAGREE"),
        ],
        judge=[],
    )
    record = run(o)
    assert record.state == SessionState.AWAITING_HUMAN
    assert "disagreement repeated" in record.outcome.reason
    assert "RVW-001" in record.outcome.reason


# ---------------------------------------------------------------------
# 17. Secrets are redacted.
# ---------------------------------------------------------------------
def test_scenario_17_secret_redaction(task_file, tmp_path, monkeypatch):
    monkeypatch.setenv("WIDGET_SECRET_TOKEN", "super-secret-env-value-42")
    leaky = PROPOSAL_V1 + (
        "\n## Notes\n\nAPI key sk-ant-abcdef1234567890abcdef and "
        "token super-secret-env-value-42.\n"
    )
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[architect_proposal_response(leaky), architect_agree_response()],
        reviewer=[reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    proposal_text = o.store.proposal_path(1).read_text()
    assert "sk-ant-abcdef1234567890abcdef" not in proposal_text
    assert "super-secret-env-value-42" not in proposal_text
    assert "[REDACTED]" in proposal_text
    for log in o.store.logs_dir.glob("*.log"):
        assert "super-secret-env-value-42" not in log.read_text()


# ---------------------------------------------------------------------
# 18. Read-only mode prevents repository modification.
# ---------------------------------------------------------------------
def test_scenario_18_read_only_mode(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[architect_proposal_response(PROPOSAL_V1), architect_agree_response()],
        reviewer=[reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    # every agent invocation was flagged read-only (adapters translate this
    # to --permission-mode plan / --sandbox read-only)
    for adapter in o._adapters.values():
        for request in adapter.invocations:
            assert request.read_only is True


# ---------------------------------------------------------------------
# Agent cwd: workspace.root resolves against the session repo root.
# ---------------------------------------------------------------------
def test_agent_cwd_is_session_repo_root(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[architect_proposal_response(PROPOSAL_V1), architect_agree_response()],
        reviewer=[reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)],
        judge=[approve_judge()],
    )
    run(o)
    for adapter in o._adapters.values():
        for request in adapter.invocations:
            assert request.cwd == tmp_path.resolve()


# ---------------------------------------------------------------------
# Judge arbitration: reviewer churn triggers arbitration; overruled
# findings are binding; debate recovers and the Judge approves normally.
# ---------------------------------------------------------------------
def test_churn_triggers_arbitration_then_approval(task_file, tmp_path):
    PROPOSAL_V3B = PROPOSAL_V2 + "\n## Hardening\n\nStaging paths are O_EXCL-created.\n"
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(reviewerChurnLimit=2),
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_proposal_response(PROPOSAL_V2, decision="REVISED",
                finding_responses=[{"finding_id": "RVW-001", "action": "FIXED",
                                    "response": "fixed"}]),
            architect_proposal_response(PROPOSAL_V3B, decision="REVISED",
                finding_responses=[{"finding_id": "RVW-002", "action": "DEFENDED",
                                    "response": "out of scope"}]),
            architect_agree_response(),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("REVISE", new_findings=[BLOCKING_FINDING]),
            reviewer_response("REVISE", new_findings=[dict(
                BLOCKING_FINDING, title="RVW-001 remains unresolved")]),   # churn 1
            reviewer_response("REVISE", new_findings=[dict(
                BLOCKING_FINDING, title="RVW-002 reopened via RVW-001")]),  # churn 2
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
        ],
        judge=[
            judge_response("REVISE", markdown="Arbitration ruling.",
                finding_verdicts=[
                    {"finding_id": "RVW-001", "verdict": "OVERRULED",
                     "notes": "already fixed in v2"},
                    {"finding_id": "RVW-002", "verdict": "OVERRULED",
                     "notes": "disproportionate to task scope"},
                    {"finding_id": "RVW-003", "verdict": "OVERRULED",
                     "notes": "re-raise without new evidence"},
                ]),
            approve_judge(),
        ],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    assert record.arbitration_used is True
    registry = FindingsRegistry.load(o.store.findings_json)
    for fid in ("RVW-001", "RVW-002", "RVW-003"):
        assert registry.get(fid).status == FindingStatus.SUPERSEDED
    arb_files = list(o.store.judgments_dir.glob("arbitration-*.md"))
    assert len(arb_files) == 1
    decisions = o.store.decisions_md.read_text()
    assert "Judge arbitration triggered" in decisions
    assert "3 finding(s) overruled" in decisions


# ---------------------------------------------------------------------
# Judge arbitration: round-limit deadlock grants bonus rounds; upheld
# findings must still be fixed before consensus.
# ---------------------------------------------------------------------
def test_round_limit_arbitration_extends_debate(task_file, tmp_path):
    PROPOSAL_V3C = PROPOSAL_V2 + "\n## Recovery\n\nPartial imports roll back.\n"
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(maxDebateRounds=2, arbitrationBonusRounds=2,
                           reviewerChurnLimit=99),
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_proposal_response(PROPOSAL_V2, decision="REVISED",
                finding_responses=[{"finding_id": "RVW-001", "action": "FIXED",
                                    "response": "fixed"}]),
            architect_proposal_response(PROPOSAL_V3C, decision="REVISED",
                finding_responses=[{"finding_id": "RVW-002", "action": "FIXED",
                                    "response": "fixed"}]),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("REVISE", new_findings=[BLOCKING_FINDING]),
            reviewer_response("REVISE", resolved_finding_ids=["RVW-001"],
                new_findings=[dict(BLOCKING_FINDING, title="No rollback")]),
            reviewer_response("APPROVE_FOR_JUDGE", resolved_finding_ids=["RVW-002"],
                              confidence=0.95),
        ],
        judge=[
            judge_response("REVISE", markdown="Arbitration: rollback concern is valid.",
                finding_verdicts=[{"finding_id": "RVW-002", "verdict": "UPHELD",
                                   "notes": "rollback genuinely required"}]),
            approve_judge(),
        ],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    assert record.round == 3            # beyond the base limit of 2
    assert record.round_extension == 2
    registry = FindingsRegistry.load(o.store.findings_json)
    # upheld finding was NOT superseded; the reviewer resolved it after the fix
    assert registry.get("RVW-002").status == FindingStatus.RESOLVED


# ---------------------------------------------------------------------
# Arbitration unavailable (disabled): churn escalates to a human.
# ---------------------------------------------------------------------
def test_churn_without_arbitration_escalates_to_human(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(reviewerChurnLimit=1, judgeArbitration=False),
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_proposal_response(PROPOSAL_V2, decision="REVISED",
                finding_responses=[{"finding_id": "RVW-001", "action": "FIXED",
                                    "response": "fixed"}]),
        ],
        reviewer=[
            reviewer_response("REVISE", new_findings=[BLOCKING_FINDING]),
            reviewer_response("REVISE", new_findings=[dict(
                BLOCKING_FINDING, title="RVW-001 remains unresolved")]),
        ],
        judge=[],
    )
    record = run(o)
    assert record.state == SessionState.AWAITING_HUMAN
    assert "arbitration unavailable" in record.outcome.reason
    assert "churn" in record.outcome.reason


# ---------------------------------------------------------------------
# Arbitration can itself demand human input.
# ---------------------------------------------------------------------
def test_arbitration_human_required(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(reviewerChurnLimit=1),
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_proposal_response(PROPOSAL_V2, decision="REVISED",
                finding_responses=[{"finding_id": "RVW-001", "action": "FIXED",
                                    "response": "fixed"}]),
        ],
        reviewer=[
            reviewer_response("REVISE", new_findings=[BLOCKING_FINDING]),
            reviewer_response("REVISE", new_findings=[dict(
                BLOCKING_FINDING, title="RVW-001 remains unresolved")]),
        ],
        judge=[
            judge_response("HUMAN_REQUIRED",
                markdown="The dispute hinges on a risk-tolerance decision."),
        ],
    )
    record = run(o)
    assert record.state == SessionState.AWAITING_HUMAN
    assert "judge requires human input" in record.outcome.reason


# ---------------------------------------------------------------------
# Adaptive model escalation: architect revises with the escalation model
# while contested (reopened / re-raised) findings are open, and reverts
# once they are cleared.
# ---------------------------------------------------------------------
def test_architect_model_escalation_on_contested_findings(task_file, tmp_path):
    from council_fixtures import mock_config as _mc
    config = _mc(reviewerChurnLimit=99)
    config.agents.architect.model = "sonnet"
    config.agents.architect.escalationModel = "opus"
    o = build_orchestrator(
        task_file, tmp_path,
        config=config,
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_proposal_response(PROPOSAL_V2, decision="REVISED",
                finding_responses=[{"finding_id": "RVW-001", "action": "FIXED",
                                    "response": "fixed"}]),
            architect_proposal_response(PROPOSAL_V3, decision="REVISED",
                finding_responses=[{"finding_id": "RVW-001", "action": "FIXED",
                                    "response": "fixed harder"}]),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("REVISE", new_findings=[BLOCKING_FINDING]),
            # reviewer reopens RVW-001 -> contested -> escalation kicks in
            reviewer_response("REVISE", reopened_finding_ids=["RVW-001"]),
            reviewer_response("APPROVE_FOR_JUDGE",
                              resolved_finding_ids=["RVW-001"], confidence=0.95),
        ],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED

    overrides = {
        r.invocation_id: r.model_override
        for a in o._adapters.values() for r in a.invocations
    }
    # revise after plain REVISE (round 1): base model
    assert overrides["revise-r001-j00-architect-a1"] is None
    # revise after the reopen (round 2): escalated
    assert overrides["revise-r002-j00-architect-a1"] == "opus"
    # confirmation after everything resolved: back to base
    assert overrides["confirm-r003-j00-architect-a1"] is None
    # audit trail records the escalation
    decisions = o.store.decisions_md.read_text()
    assert "escalated to 'opus' for contested findings: RVW-001" in decisions


# ---------------------------------------------------------------------
# Raw logs from re-run invocations (resume) must never be dropped.
# ---------------------------------------------------------------------
def test_rerun_raw_logs_are_preserved(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[architect_proposal_response(PROPOSAL_V1), architect_agree_response()],
        reviewer=[reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)],
        judge=[approve_judge()],
    )
    run(o)
    o._write_raw_logs("review-r001-j00-reviewer-a1", "second run output", "err2")
    first = o.store.raw_log_path("review-r001-j00-reviewer-a1", "stdout").read_text()
    second = o.store.raw_log_path("review-r001-j00-reviewer-a1-run2", "stdout").read_text()
    assert "second run output" not in first
    assert second == "second run output"


# ---------------------------------------------------------------------
# Failure classification: transient drops retry on their own budget;
# usage-limit and auth failures fail fast with actionable reasons.
# ---------------------------------------------------------------------
CONNECTION_DROP = {"behavior": "fail",
                   "response": "API Error: Connection closed mid-response."}


def _fast_transients(**kw):
    kw.setdefault("transientBackoffSeconds", 0)
    return mock_config(**kw)


def test_connection_drops_retry_without_burning_failure_budget(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        config=_fast_transients(maxAgentFailures=0),  # zero tolerance for real failures
        architect=[architect_proposal_response(PROPOSAL_V1), architect_agree_response()],
        reviewer=[CONNECTION_DROP, CONNECTION_DROP,
                  reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    # two drops consumed zero agent-failure budget
    assert record.agent_failures.get("reviewer", 0) == 0
    assert "[TRANSIENT]" in o.store.transcript_md.read_text()


def test_persistent_connection_drops_eventually_fail(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        config=_fast_transients(maxTransientRetries=2),
        architect=[architect_proposal_response(PROPOSAL_V1)],
        reviewer=[CONNECTION_DROP, CONNECTION_DROP, CONNECTION_DROP],
        judge=[],
    )
    record = run(o)
    assert record.state == SessionState.FAILED
    assert "transient API/network failures" in record.outcome.reason
    assert "ai-council resume" in record.outcome.reason


def test_usage_limit_fails_fast_with_reset_time(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[{"behavior": "fail",
                    "response": "You've hit your session limit · resets 3:10pm "
                                "(America/Santo_Domingo)"}],
        reviewer=[], judge=[],
    )
    record = run(o)
    assert record.state == SessionState.FAILED
    assert "[USAGE_LIMIT]" in record.outcome.reason
    assert "resets 3:10pm" in record.outcome.reason
    assert "Wait for the limit to reset" in record.outcome.reason
    # exactly one attempt — no retries were burned against the wall
    assert len(o._adapters["architect"].invocations) == 1


def test_auth_failure_fails_fast_with_instruction(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[{"behavior": "fail",
                    "response": "Failed to authenticate: OAuth session expired "
                                "and could not be refreshed"}],
        reviewer=[], judge=[],
    )
    record = run(o)
    assert record.state == SessionState.FAILED
    assert "[AUTH]" in record.outcome.reason
    assert "Re-authenticate" in record.outcome.reason
    assert len(o._adapters["architect"].invocations) == 1


# ---------------------------------------------------------------------
# Delta revisions: the architect sends edit blocks; the orchestrator
# assembles, hashes, and stores the complete new version.
# ---------------------------------------------------------------------
OLD_LINE = "- REQ-002: upsert keyed on widget SKU makes re-runs idempotent."
NEW_LINE = ("- REQ-002: upsert keyed on widget SKU makes re-runs idempotent; a\n"
            "  unique constraint on SKU enforces it at the database level.")
DELTA_EDIT = (
    "Hardening idempotency per RVW-001.\n\n"
    f"<<<<<<< SEARCH\n{OLD_LINE}\n=======\n{NEW_LINE}\n>>>>>>> REPLACE\n"
)
BAD_DELTA = (
    "Fixing.\n\n<<<<<<< SEARCH\nthis text is not in the proposal\n"
    "=======\nreplacement\n>>>>>>> REPLACE\n"
)


def test_delta_revision_applied_by_orchestrator(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_proposal_response(DELTA_EDIT, decision="REVISED",
                finding_responses=[{"finding_id": "RVW-001", "action": "FIXED",
                                    "response": "constraint added"}]),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("REVISE", new_findings=[BLOCKING_FINDING]),
            reviewer_response("APPROVE_FOR_JUDGE", resolved_finding_ids=["RVW-001"],
                              confidence=0.95),
        ],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    v2 = o.store.proposal_path(2).read_text()
    expected = PROPOSAL_V1.replace(OLD_LINE, NEW_LINE).strip() + "\n"
    assert v2 == expected                       # exact assembled document
    assert "Hardening idempotency" not in v2    # commentary discarded
    from ai_council.hashing import sha256_text
    assert record.proposals[-1].sha256 == sha256_text(v2)  # hash contract intact


def test_delta_patch_failure_is_repaired(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_proposal_response(BAD_DELTA, decision="REVISED"),   # bad anchors
            architect_proposal_response(DELTA_EDIT, decision="REVISED"),  # repair
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("REVISE", new_findings=[BLOCKING_FINDING]),
            reviewer_response("APPROVE_FOR_JUDGE", resolved_finding_ids=["RVW-001"],
                              confidence=0.95),
        ],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    assert record.latest_proposal.version == 2
    purposes = [inv.purpose for inv in record.invocations]
    assert "revise-fix1" in purposes
    assert "SEARCH text not found" in o.store.transcript_md.read_text()


def test_delta_patch_failures_exhaust(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(maxFormatRetries=1),
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_proposal_response(BAD_DELTA, decision="REVISED"),
            architect_proposal_response(BAD_DELTA, decision="REVISED"),
        ],
        reviewer=[reviewer_response("REVISE", new_findings=[BLOCKING_FINDING])],
        judge=[],
    )
    record = run(o)
    assert record.state == SessionState.FAILED
    assert "delta edits failed to apply" in record.outcome.reason


# ---------------------------------------------------------------------
# Severity discipline: reviewer BLOCKING findings that cite no violated
# requirement are downgraded to MAJOR and cannot block consensus.
# ---------------------------------------------------------------------
def test_uncited_blocking_finding_downgraded(task_file, tmp_path):
    scope_creep = {
        "title": "Should also support XML imports",
        "detail": "Robustness idea beyond the stated task.",
        "severity": "BLOCKING",   # no "violates" -> downgraded
    }
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[architect_proposal_response(PROPOSAL_V1), architect_agree_response()],
        # reviewer raises the uncited finding yet approves; without the
        # downgrade the open BLOCKING finding would sink consensus
        reviewer=[reviewer_response("APPROVE_FOR_JUDGE", new_findings=[scope_creep],
                                    confidence=0.95)],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    registry = FindingsRegistry.load(o.store.findings_json)
    finding = registry.get("RVW-001")
    assert finding.severity.value == "MAJOR"
    assert any("downgraded BLOCKING->MAJOR" in h for h in finding.history)
    assert "downgraded BLOCKING->MAJOR" in o.store.transcript_md.read_text()


def test_cited_blocking_finding_still_blocks(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        config=mock_config(maxDebateRounds=1, judgeArbitration=False),
        architect=[architect_proposal_response(PROPOSAL_V1), architect_agree_response(),
                   architect_echo_response("AGREED", confidence=0.95)],
        # BLOCKING with a cited violation stays blocking -> consensus fails
        reviewer=[reviewer_response("APPROVE_FOR_JUDGE",
                                    new_findings=[BLOCKING_FINDING], confidence=0.95)],
        judge=[],
    )
    record = run(o)
    assert record.state == SessionState.BLOCKED
    registry = FindingsRegistry.load(o.store.findings_json)
    assert registry.get("RVW-001").severity.value == "BLOCKING"


# ---------------------------------------------------------------------
# Approve-with-conditions: reviewer-authored minor edits skip the extra
# review round once the architect accepts them.
# ---------------------------------------------------------------------
COND_EDITS = (
    f"<<<<<<< SEARCH\n{OLD_LINE}\n=======\n{NEW_LINE}\n>>>>>>> REPLACE\n"
)


def test_approve_with_conditions_fast_path(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_agree_response(),      # accepts the reviewer's conditions
        ],
        reviewer=[
            reviewer_response("APPROVE_WITH_CONDITIONS", confidence=0.95,
                              condition_edits=COND_EDITS),
        ],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    # only ONE review round happened — the fast path saved the re-review
    assert record.round == 1
    assert len(o._adapters["reviewer"].invocations) == 1
    # v2 is exactly the reviewer's edits applied to v1
    v2 = o.store.proposal_path(2).read_text()
    assert v2 == PROPOSAL_V1.replace(OLD_LINE, NEW_LINE).strip() + "\n"
    from ai_council.hashing import sha256_text
    assert record.conditional_binding["bound_hash"] == sha256_text(v2)
    decisions = o.store.decisions_md.read_text()
    assert "approved WITH CONDITIONS" in decisions
    assert "reviewer's approval is bound to it" in decisions


def test_conditions_rejected_by_architect_resumes_debate(task_file, tmp_path):
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_echo_response("DISAGREE", confidence=0.95),  # rejects edits
            architect_proposal_response(PROPOSAL_V2, decision="REVISED"),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("APPROVE_WITH_CONDITIONS", confidence=0.95,
                              condition_edits=COND_EDITS),
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
        ],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    assert record.round == 2                 # normal loop resumed
    assert record.pending_conditions == {}
    assert "rejected the reviewer's conditions" in o.store.decisions_md.read_text()


def test_bad_condition_edits_fall_back_to_revise(task_file, tmp_path):
    bad = "<<<<<<< SEARCH\nnot present anywhere\n=======\nx\n>>>>>>> REPLACE\n"
    o = build_orchestrator(
        task_file, tmp_path,
        architect=[
            architect_proposal_response(PROPOSAL_V1),
            architect_proposal_response(PROPOSAL_V2, decision="REVISED"),
            architect_agree_response(),
        ],
        reviewer=[
            reviewer_response("APPROVE_WITH_CONDITIONS", confidence=0.95,
                              condition_edits=bad),
            reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95),
        ],
        judge=[approve_judge()],
    )
    record = run(o)
    assert record.state == SessionState.APPROVED
    assert "condition edits failed to apply" in o.store.transcript_md.read_text()
