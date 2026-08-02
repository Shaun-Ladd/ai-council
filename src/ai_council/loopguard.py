"""Loop and stagnation detection.

Detects:
- debate-round and judge-cycle limit exhaustion
- repeated blocking disagreement (same disagreement signature repeating)
- proposal-hash cycles (a "new" version reusing a previously seen hash)
- no-material-change responses after a revision request
"""
from __future__ import annotations

import hashlib
from typing import Optional

from .config import SessionLimits
from .models import SessionRecord
from .registry import FindingsRegistry


class LoopEscalation(Exception):
    """Raised when a termination rule fires. ``target`` is the terminal state
    name the orchestrator should move to (BLOCKED / AWAITING_HUMAN / FAILED)."""

    def __init__(self, target: str, reason: str):
        super().__init__(reason)
        self.target = target
        self.reason = reason


def disagreement_signature(
    architect_decision: str, reviewer_decision: str, registry: FindingsRegistry
) -> str:
    """Stable signature of the current disagreement: who disagrees and which
    blocking findings remain open."""
    open_blocking = ",".join(sorted(f.id for f in registry.open_blocking()))
    raw = f"{architect_decision}|{reviewer_decision}|{open_blocking}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def check_round_limit(record: SessionRecord, limits: SessionLimits) -> None:
    if record.round >= limits.maxDebateRounds:
        raise LoopEscalation(
            "BLOCKED",
            f"Maximum debate rounds reached ({limits.maxDebateRounds}) without candidate consensus.",
        )


def check_judge_cycle_limit(record: SessionRecord, limits: SessionLimits) -> None:
    if record.judge_cycle >= limits.maxJudgeCycles:
        raise LoopEscalation(
            "BLOCKED",
            f"Maximum Judge cycles reached ({limits.maxJudgeCycles}) without approval.",
        )


def note_disagreement(
    record: SessionRecord,
    limits: SessionLimits,
    architect_decision: str,
    reviewer_decision: str,
    registry: FindingsRegistry,
) -> None:
    """Record a disagreement occurrence; escalate when the same disagreement
    repeats ``repeatedDisagreementLimit`` times."""
    sig = disagreement_signature(architect_decision, reviewer_decision, registry)
    count = record.disagreement_counts.get(sig, 0) + 1
    record.disagreement_counts[sig] = count
    if count >= limits.repeatedDisagreementLimit:
        open_ids = ", ".join(f.id for f in registry.open_blocking()) or "none recorded"
        raise LoopEscalation(
            "AWAITING_HUMAN",
            f"The same blocking disagreement repeated {count} times "
            f"(open blocking findings: {open_ids}). Human arbitration is required.",
        )


def check_new_proposal_hash(
    record: SessionRecord,
    new_hash: str,
    *,
    revision_requested: bool,
    previous_hash: Optional[str],
) -> None:
    """Validate a newly produced proposal hash against loop rules.

    Callers add the hash to ``record.seen_proposal_hashes`` only after this
    check passes.
    """
    if revision_requested and previous_hash is not None and new_hash == previous_hash:
        raise LoopEscalation(
            "BLOCKED",
            "Architect returned a proposal with no material change after a revision request.",
        )
    if new_hash in record.seen_proposal_hashes:
        raise LoopEscalation(
            "BLOCKED",
            "Proposal-hash cycle detected: the architect resubmitted a previously seen proposal.",
        )
