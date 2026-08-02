import pytest

from ai_council.models import SessionState
from ai_council.statemachine import IllegalTransition, is_terminal, validate_transition


def test_legal_flow():
    flow = [
        SessionState.INITIALIZING,
        SessionState.EXTRACTING_REQUIREMENTS,
        SessionState.ARCHITECT_PROPOSING,
        SessionState.REVIEWER_REVIEWING,
        SessionState.ARCHITECT_REVISING,
        SessionState.REVIEWER_REVIEWING,
        SessionState.CANDIDATE_CONSENSUS,
        SessionState.JUDGE_EVALUATING,
        SessionState.JUDGE_REJECTED,
        SessionState.ARCHITECT_REVISING,
    ]
    for current, target in zip(flow, flow[1:]):
        validate_transition(current, target)


def test_illegal_transitions():
    with pytest.raises(IllegalTransition):
        validate_transition(SessionState.INITIALIZING, SessionState.JUDGE_EVALUATING)
    with pytest.raises(IllegalTransition):
        validate_transition(SessionState.REVIEWER_REVIEWING, SessionState.APPROVED)
    with pytest.raises(IllegalTransition):
        validate_transition(SessionState.APPROVED, SessionState.ARCHITECT_REVISING)


def test_failed_and_cancelled_always_reachable():
    for state in SessionState:
        if is_terminal(state):
            continue
        validate_transition(state, SessionState.FAILED)
        validate_transition(state, SessionState.CANCELLED)


def test_terminal_states_are_dead_ends():
    for state in (SessionState.APPROVED, SessionState.FAILED, SessionState.BLOCKED,
                  SessionState.CANCELLED, SessionState.AWAITING_HUMAN):
        assert is_terminal(state)
        with pytest.raises(IllegalTransition):
            validate_transition(state, SessionState.FAILED)


def test_judge_can_approve():
    validate_transition(SessionState.JUDGE_EVALUATING, SessionState.APPROVED)
