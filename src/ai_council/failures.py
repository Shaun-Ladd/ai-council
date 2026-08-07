"""Classification of agent-invocation failures.

Turns raw process output into an actionable failure kind so the orchestrator
can choose the right policy per class:

- TRANSIENT (connection drops, server overload): retry with backoff on a
  dedicated budget — these say nothing about the agent or the debate.
- USAGE_LIMIT: fail fast with the reset information; retrying burns budget
  against a wall that only time removes.
- AUTH: fail fast with a re-login instruction; retrying cannot succeed.
- TIMEOUT / AGENT: the classic failure budget (``maxAgentFailures``).
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass


class FailureKind(str, enum.Enum):
    TRANSIENT = "TRANSIENT"        # dropped connection, overloaded server
    USAGE_LIMIT = "USAGE_LIMIT"    # plan/session/rate limit exhausted
    AUTH = "AUTH"                  # authentication / login problems
    TIMEOUT = "TIMEOUT"            # our own wall-clock timeout fired
    AGENT = "AGENT"                # anything else (unknown nonzero exit)


@dataclass
class FailureDiagnosis:
    kind: FailureKind
    detail: str

    @property
    def retry_transiently(self) -> bool:
        return self.kind == FailureKind.TRANSIENT

    @property
    def fail_fast(self) -> bool:
        return self.kind in (FailureKind.USAGE_LIMIT, FailureKind.AUTH)


_TRANSIENT_PATTERNS = [
    r"connection closed mid-response",
    r"api error: connection",
    r"connection (?:error|reset|refused|aborted)",
    r"econnreset|etimedout|econnrefused|epipe",
    r"socket hang ?up",
    r"fetch failed",
    r"network error",
    r"stream(?:ing)? (?:error|interrupted|disconnected)",
    r"\boverloaded\b",
    r"overloaded_error",
    r"server_error",
    r"internal server error",
    r"\b(?:500|502|503|504|529)\b.{0,40}(?:error|overloaded|unavailable|bad gateway)",
    r"service unavailable",
]

_USAGE_LIMIT_PATTERNS = [
    r"hit your (?:session|usage|weekly|plan) limit",
    r"usage limit (?:reached|exceeded)",
    r"rate.?limit",
    r"\b429\b",
    r"quota (?:exceeded|reached)",
    r"too many requests",
    r"out of (?:usage|credits)",
]

_AUTH_PATTERNS = [
    r"failed to authenticate",
    r"oauth .{0,40}(?:expired|failed|invalid|could not)",
    r"not logged in",
    r"please (?:log ?in|sign ?in|run /login)",
    r"\b401\b|unauthorized",
    r"invalid (?:api key|x-api-key|token)",
    r"authentication[_ ]error",
    r"credit balance is too low",
    r"billing",
]

_RESET_RE = re.compile(r"resets? (?:in |at )?[^\n.·]{1,60}", re.IGNORECASE)


def _search(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def classify_failure(
    stdout: str, stderr: str, *, exit_code: int | None, timed_out: bool
) -> FailureDiagnosis:
    if timed_out:
        return FailureDiagnosis(FailureKind.TIMEOUT, "invocation exceeded its wall-clock timeout")
    text = f"{stdout}\n{stderr}"

    matched = _search(_USAGE_LIMIT_PATTERNS, text)
    if matched:
        reset = _RESET_RE.search(text)
        detail = f"usage limit: {matched!r}"
        if reset:
            detail += f" ({reset.group(0).strip()})"
        return FailureDiagnosis(FailureKind.USAGE_LIMIT, detail)

    matched = _search(_AUTH_PATTERNS, text)
    if matched:
        return FailureDiagnosis(FailureKind.AUTH, f"authentication failure: {matched!r}")

    matched = _search(_TRANSIENT_PATTERNS, text)
    if matched:
        return FailureDiagnosis(FailureKind.TRANSIENT, f"transient API/network failure: {matched!r}")

    return FailureDiagnosis(
        FailureKind.AGENT, f"exited with code {exit_code}"
    )
