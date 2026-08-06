"""Loop and stagnation detection.

Detects:
- debate-round and judge-cycle limit exhaustion
- repeated blocking disagreement (same disagreement signature repeating)
- proposal-hash cycles (a "new" version reusing a previously seen hash)
- no-material-change responses after a revision request
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from .config import SessionLimits
from .models import Finding, SessionRecord
from .registry import FindingsRegistry

_FINDING_ID_RE = re.compile(r"\b(?:RVW|JDG|FND)-\d{3}\b")


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
    limit = limits.maxDebateRounds + record.round_extension
    if record.round >= limit:
        raise LoopEscalation(
            "BLOCKED",
            f"Maximum debate rounds reached ({limit}) without candidate consensus.",
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


def lineage_reraise_ids(added: list[Finding], registry: FindingsRegistry) -> list[str]:
    """IDs of newly added findings that reference an existing finding's ID
    in their title/detail (a re-raise of the same lineage under a new ID)."""
    ids = []
    for f in added:
        for ref in _FINDING_ID_RE.findall(f"{f.title} {f.detail}"):
            if ref != f.id and registry.has(ref):
                ids.append(f.id)
                break
    return ids


def review_churn_signal(
    *,
    added: list[Finding],
    resolved_ids: list[str],
    reopened_ids: list[str],
    decision: str,
    prior_open_count: int,
    registry: FindingsRegistry,
) -> Optional[str]:
    """Return a churn reason if this review round shows reviewer churn.

    Churn signals:
    - a new finding whose title/detail references an existing finding's ID
      (a re-raise of the same lineage under a fresh ID), or a reopen
    - a no-progress round: findings were open going in, none were resolved,
      yet new findings were raised
    """
    if decision == "APPROVE_FOR_JUDGE":
        return None
    reraised = lineage_reraise_ids(added, registry)
    if reraised:
        return f"new finding {reraised[0]} re-raises an existing finding"
    if reopened_ids:
        return f"reviewer reopened findings without judge authority: {', '.join(reopened_ids)}"
    if prior_open_count > 0 and not resolved_ids and added:
        return (
            f"no-progress round: {prior_open_count} findings were open, none "
            f"resolved, {len(added)} new raised"
        )
    return None


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
