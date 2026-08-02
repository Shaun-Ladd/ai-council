import pytest

from ai_council.config import SessionLimits
from ai_council.loopguard import (
    LoopEscalation,
    check_judge_cycle_limit,
    check_new_proposal_hash,
    check_round_limit,
    note_disagreement,
)
from ai_council.models import FindingSeverity, NewFinding, SessionRecord
from ai_council.registry import FindingsRegistry


def _record(**kw):
    return SessionRecord(id="s", **kw)


def test_round_limit():
    limits = SessionLimits(maxDebateRounds=2)
    check_round_limit(_record(round=1), limits)
    with pytest.raises(LoopEscalation) as exc:
        check_round_limit(_record(round=2), limits)
    assert exc.value.target == "BLOCKED"


def test_judge_cycle_limit():
    limits = SessionLimits(maxJudgeCycles=1)
    check_judge_cycle_limit(_record(judge_cycle=0), limits)
    with pytest.raises(LoopEscalation):
        check_judge_cycle_limit(_record(judge_cycle=1), limits)


def test_repeated_disagreement_escalates_to_human():
    limits = SessionLimits(repeatedDisagreementLimit=2)
    record = _record()
    registry = FindingsRegistry()
    registry.add_new([NewFinding(title="x", severity=FindingSeverity.BLOCKING)],
                     source_role="reviewer", proposal_version=1, round_no=1)
    note_disagreement(record, limits, "DISAGREE", "DISAGREE", registry)
    with pytest.raises(LoopEscalation) as exc:
        note_disagreement(record, limits, "DISAGREE", "DISAGREE", registry)
    assert exc.value.target == "AWAITING_HUMAN"


def test_different_disagreements_counted_separately():
    limits = SessionLimits(repeatedDisagreementLimit=2)
    record = _record()
    registry = FindingsRegistry()
    note_disagreement(record, limits, "DISAGREE", "REVISE", registry)
    note_disagreement(record, limits, "AGREED", "DISAGREE", registry)  # no raise
    assert len(record.disagreement_counts) == 2


def test_hash_cycle_detected():
    record = _record(seen_proposal_hashes=["h1", "h2"])
    with pytest.raises(LoopEscalation, match="cycle"):
        check_new_proposal_hash(record, "h1", revision_requested=False, previous_hash="h2")
    check_new_proposal_hash(record, "h3", revision_requested=False, previous_hash="h2")


def test_no_material_change_after_revision_request():
    record = _record(seen_proposal_hashes=["h1"])
    with pytest.raises(LoopEscalation, match="no material change"):
        check_new_proposal_hash(record, "h1", revision_requested=True, previous_hash="h1")
