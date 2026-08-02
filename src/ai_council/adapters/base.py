"""Generic agent adapter interface.

The orchestrator never talks to a specific CLI directly; it invokes an
``AgentAdapter`` bound to a role (architect / reviewer / judge / extractor)
through configuration. Any adapter can fill any role.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class InvocationRequest:
    prompt: str
    invocation_id: str
    role: str
    purpose: str = ""              # e.g. "proposal", "review", "judgment", "format-repair"
    timeout_seconds: int = 900
    cwd: Optional[Path] = None
    read_only: bool = True


@dataclass
class InvocationResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_seconds: float = 0.0
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False
    argv: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.cancelled


class AgentAdapterError(Exception):
    pass


class AgentAdapter(abc.ABC):
    """Interface all agent adapters implement."""

    name: str = "agent"

    @abc.abstractmethod
    def invoke(self, request: InvocationRequest) -> InvocationResult:
        """Run the agent once with the given prompt and return the result.

        Implementations must never raise for ordinary process failures
        (non-zero exit, timeout); those are reported via the result so the
        orchestrator can apply retry/escalation policy uniformly.
        """

    def doctor(self) -> tuple[bool, str]:
        """Return (available, human-readable detail) for `ai-council doctor`."""
        return True, "no checks implemented"
