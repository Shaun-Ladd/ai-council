from ai_council.config import AgreementConfig
from ai_council.consensus import check_candidate_consensus, missing_requirement_ids
from ai_council.models import (
    ArchitectStatus,
    FindingSeverity,
    NewFinding,
    ProposalRef,
    Requirement,
    RequirementsDoc,
    ReviewerStatus,
)
from ai_council.registry import FindingsRegistry

HASH = "a" * 64
PROPOSAL = ProposalRef(version=2, sha256=HASH, path="/tmp/p.md")
TEXT = "covers REQ-001 and REQ-002"
REQS = RequirementsDoc(
    task_hash="t" * 64,
    requirements=[
        Requirement(id="REQ-001", text="x"),
        Requirement(id="REQ-002", text="y"),
    ],
)


def _architect(**kw):
    base = dict(role="architect", decision="AGREED", proposal_version=2,
                proposal_hash=HASH, confidence=0.95)
    base.update(kw)
    return ArchitectStatus.model_validate(base)


def _reviewer(**kw):
    base = dict(role="reviewer", decision="APPROVE_FOR_JUDGE", proposal_version=2,
                proposal_hash=HASH, confidence=0.95)
    base.update(kw)
    return ReviewerStatus.model_validate(base)


def _check(architect=None, reviewer=None, registry=None, text=TEXT, reqs=REQS,
           agreement=None):
    return check_candidate_consensus(
        architect if architect is not None else _architect(),
        reviewer if reviewer is not None else _reviewer(),
        PROPOSAL, text, registry or FindingsRegistry(), reqs,
        agreement or AgreementConfig(),
    )


def test_consensus_ok():
    assert _check().ok


def test_architect_not_agreed():
    result = _check(architect=_architect(decision="DISAGREE"))
    assert not result.ok
    assert any("not AGREED" in r for r in result.reasons)


def test_reviewer_not_approving():
    assert not _check(reviewer=_reviewer(decision="REVISE")).ok


def test_version_mismatch():
    result = _check(reviewer=_reviewer(proposal_version=1))
    assert any("references proposal v1" in r for r in result.reasons)


def test_hash_mismatch():
    result = _check(architect=_architect(proposal_hash="b" * 64))
    assert any("stale or unknown proposal hash" in r for r in result.reasons)


def test_hash_check_can_be_disabled():
    agreement = AgreementConfig(requireMatchingProposalHash=False)
    assert _check(architect=_architect(proposal_hash="b" * 64), agreement=agreement).ok


def test_open_blocking_finding_blocks():
    registry = FindingsRegistry()
    registry.add_new(
        [NewFinding(title="bad", severity=FindingSeverity.BLOCKING)],
        source_role="reviewer", proposal_version=2, round_no=1,
    )
    result = _check(registry=registry)
    assert any("blocking findings" in r for r in result.reasons)


def test_unresolved_objections_block():
    result = _check(architect=_architect(unresolved_objections=["still wrong"]))
    assert not result.ok


def test_missing_requirement_blocks():
    result = _check(text="only REQ-001 is covered")
    assert any("REQ-002" in r for r in result.reasons)
    assert missing_requirement_ids(REQS, "nothing") == ["REQ-001", "REQ-002"]


def test_low_confidence_blocks():
    result = _check(reviewer=_reviewer(confidence=0.5))
    assert any("confidence" in r for r in result.reasons)
