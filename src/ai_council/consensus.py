"""Candidate-consensus rules.

Pure functions: given the latest architect status, latest reviewer status,
the authoritative proposal reference, the findings registry, and the
requirements document, decide whether candidate consensus exists.

Candidate consensus is NOT final approval; it only gates Judge evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import AgreementConfig
from .models import (
    ArchitectDecision,
    ArchitectStatus,
    ProposalRef,
    RequirementsDoc,
    ReviewerDecision,
    ReviewerStatus,
)
from .registry import FindingsRegistry


@dataclass
class ConsensusResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return "Candidate consensus reached."
        return "No candidate consensus: " + "; ".join(self.reasons)


def missing_requirement_ids(requirements: RequirementsDoc, proposal_text: str) -> list[str]:
    """Requirement IDs that never appear in the proposal's coverage matrix.

    This is a mechanical completeness check; the Judge performs the semantic
    evaluation of whether coverage claims are actually satisfied.
    """
    return [r.id for r in requirements.requirements if r.id not in proposal_text]


def check_candidate_consensus(
    architect: ArchitectStatus | None,
    reviewer: ReviewerStatus | None,
    proposal: ProposalRef | None,
    proposal_text: str,
    registry: FindingsRegistry,
    requirements: RequirementsDoc | None,
    agreement: AgreementConfig,
) -> ConsensusResult:
    reasons: list[str] = []

    if proposal is None:
        return ConsensusResult(False, ["no proposal exists"])
    if architect is None:
        return ConsensusResult(False, ["architect has not issued a status"])
    if reviewer is None:
        return ConsensusResult(False, ["reviewer has not issued a status"])

    # 1. Architect agreement
    if architect.decision != ArchitectDecision.AGREED:
        reasons.append(f"architect decision is {architect.decision.value}, not AGREED")

    # 2. Reviewer approval
    if reviewer.decision != ReviewerDecision.APPROVE_FOR_JUDGE:
        reasons.append(f"reviewer decision is {reviewer.decision.value}, not APPROVE_FOR_JUDGE")

    # 3. Same proposal version, matching the authoritative latest version
    if architect.proposal_version != proposal.version:
        reasons.append(
            f"architect references proposal v{architect.proposal_version}, "
            f"current is v{proposal.version}"
        )
    if reviewer.proposal_version != proposal.version:
        reasons.append(
            f"reviewer references proposal v{reviewer.proposal_version}, "
            f"current is v{proposal.version}"
        )

    # 4. Same proposal hash (also detects material change after review)
    if agreement.requireMatchingProposalHash:
        if architect.proposal_hash != proposal.sha256:
            reasons.append("architect references a stale or unknown proposal hash")
        if reviewer.proposal_hash != proposal.sha256:
            reasons.append("reviewer references a stale or unknown proposal hash")

    # 5. No unresolved blocking findings
    if agreement.requireNoBlockingFindings:
        blocking = registry.open_blocking()
        if blocking:
            ids = ", ".join(f.id for f in blocking)
            reasons.append(f"unresolved blocking findings: {ids}")

    # 6. No unresolved architect objections
    if architect.unresolved_objections:
        reasons.append(f"architect has {len(architect.unresolved_objections)} unresolved objections")

    # 7. Requirement matrix contains no unexplained missing requirements
    if requirements is not None:
        missing = missing_requirement_ids(requirements, proposal_text)
        if missing:
            reasons.append(f"proposal does not reference requirements: {', '.join(missing)}")

    # 8. Confidence thresholds
    if architect.confidence < agreement.minimumConfidence:
        reasons.append(
            f"architect confidence {architect.confidence:.2f} below "
            f"minimum {agreement.minimumConfidence:.2f}"
        )
    if reviewer.confidence < agreement.minimumConfidence:
        reasons.append(
            f"reviewer confidence {reviewer.confidence:.2f} below "
            f"minimum {agreement.minimumConfidence:.2f}"
        )

    return ConsensusResult(ok=not reasons, reasons=reasons)
