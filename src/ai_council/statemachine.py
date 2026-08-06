"""Explicit workflow state machine.

Transitions are whitelisted; anything else raises ``IllegalTransition``.
The orchestrator persists the session record after every transition.
"""
from __future__ import annotations

from .models import SessionState, TERMINAL_STATES


class IllegalTransition(Exception):
    pass


_ALWAYS_REACHABLE = {SessionState.FAILED, SessionState.CANCELLED}

ALLOWED_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.INITIALIZING: {
        SessionState.EXTRACTING_REQUIREMENTS,
        # `implement --from-session` seeds an approved plan and skips the
        # plan debate entirely
        SessionState.IMPLEMENTING,
    },
    SessionState.EXTRACTING_REQUIREMENTS: {SessionState.ARCHITECT_PROPOSING},
    SessionState.ARCHITECT_PROPOSING: {
        SessionState.REVIEWER_REVIEWING,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.REVIEWER_REVIEWING: {
        SessionState.ARCHITECT_REVISING,
        SessionState.CANDIDATE_CONSENSUS,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.ARCHITECT_REVISING: {
        SessionState.REVIEWER_REVIEWING,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.CANDIDATE_CONSENSUS: {
        SessionState.JUDGE_EVALUATING,
        # consensus re-check may fail (e.g. hash mismatch) and reopen debate
        SessionState.ARCHITECT_REVISING,
        SessionState.REVIEWER_REVIEWING,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.JUDGE_EVALUATING: {
        SessionState.APPROVED,
        SessionState.IMPLEMENTING,  # implement mode: plan approved -> build it
        SessionState.JUDGE_REJECTED,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.JUDGE_REJECTED: {
        SessionState.ARCHITECT_REVISING,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.IMPLEMENTING: {
        SessionState.IMPL_REVIEWING,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.IMPL_REVIEWING: {
        SessionState.IMPL_REVISING,
        SessionState.IMPL_CONSENSUS,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.IMPL_REVISING: {
        SessionState.IMPL_REVIEWING,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.IMPL_CONSENSUS: {
        SessionState.IMPL_JUDGING,
        SessionState.IMPL_REVISING,
        SessionState.IMPL_REVIEWING,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.IMPL_JUDGING: {
        SessionState.IMPLEMENTED,
        SessionState.IMPL_REJECTED,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.IMPL_REJECTED: {
        SessionState.IMPL_REVISING,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    },
    SessionState.IMPLEMENTED: set(),
    SessionState.APPROVED: set(),
    SessionState.AWAITING_HUMAN: set(),
    SessionState.BLOCKED: set(),
    SessionState.FAILED: set(),
    SessionState.CANCELLED: set(),
}


def validate_transition(current: SessionState, target: SessionState) -> None:
    if target in _ALWAYS_REACHABLE and current not in TERMINAL_STATES:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise IllegalTransition(f"Illegal state transition: {current.value} -> {target.value}")


def is_terminal(state: SessionState) -> bool:
    return state in TERMINAL_STATES
