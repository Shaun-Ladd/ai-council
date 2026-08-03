"""Deterministic mock adapter for tests, examples, and offline demos.

A mock agent consumes a script: an ordered list of entries, one per
invocation. Entry fields:

- ``response``: stdout text (usually markdown + <AI_COUNCIL_STATUS> block)
- ``behavior``: ``ok`` (default) | ``timeout`` | ``fail`` | ``cancel``
- ``exit_code``: exit code (default 0 for ok, 1 for fail)
- ``stderr``: stderr text

Placeholders in ``response`` are substituted from marker lines that the
orchestrator's prompt templates always include:

- ``{{PROPOSAL_VERSION}}``  <- ``PROPOSAL-VERSION: <n>``
- ``{{PROPOSAL_HASH}}``     <- ``PROPOSAL-HASH: <sha256>``

so scripted reviewers/judges can echo the exact version and hash they were
shown, exactly as a live model is instructed to do.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from .base import AgentAdapter, AgentAdapterError, InvocationRequest, InvocationResult

_VERSION_MARKER = re.compile(r"^PROPOSAL-VERSION:\s*(\S+)\s*$", re.MULTILINE)
_HASH_MARKER = re.compile(r"^PROPOSAL-HASH:\s*(\S+)\s*$", re.MULTILINE)


class MockAgentAdapter(AgentAdapter):
    name = "mock"

    def __init__(
        self,
        script: Optional[list[dict[str, Any]]] = None,
        script_path: Optional[Path | str] = None,
        loop_last: bool = False,
    ):
        if script is None and script_path is not None:
            script = load_mock_script(script_path)
        self.script: list[dict[str, Any]] = script or []
        self.loop_last = loop_last
        self.cursor = 0
        self.invocations: list[InvocationRequest] = []

    def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.invocations.append(request)
        if self.cursor >= len(self.script):
            if self.loop_last and self.script:
                entry = self.script[-1]
            else:
                raise AgentAdapterError(
                    f"Mock script exhausted after {len(self.script)} responses "
                    f"(role={request.role}, purpose={request.purpose})"
                )
        else:
            entry = self.script[self.cursor]
        self.cursor += 1

        behavior = entry.get("behavior", "ok")
        if behavior == "interrupt":
            # Simulates the user hitting Ctrl-C while this agent is running.
            raise KeyboardInterrupt("mock interrupt")
        # Simulate an implementing agent: write files into the working dir.
        for relpath, content in (entry.get("write_files") or {}).items():
            if request.cwd is None:
                raise AgentAdapterError("write_files requires a cwd on the request")
            target = Path(request.cwd) / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        response = _substitute(entry.get("response", ""), request.prompt)
        if behavior == "timeout":
            return InvocationResult(
                stdout=response, stderr=entry.get("stderr", ""), exit_code=None,
                timed_out=True, duration_seconds=float(request.timeout_seconds),
                argv=["mock"],
            )
        if behavior == "cancel":
            return InvocationResult(
                stdout=response, stderr=entry.get("stderr", ""), exit_code=None,
                cancelled=True, argv=["mock"],
            )
        default_exit = 1 if behavior == "fail" else 0
        return InvocationResult(
            stdout=response,
            stderr=entry.get("stderr", ""),
            exit_code=int(entry.get("exit_code", default_exit)),
            duration_seconds=float(entry.get("duration", 0.01)),
            argv=["mock"],
        )

    def doctor(self) -> tuple[bool, str]:
        return True, f"mock adapter with {len(self.script)} scripted responses"


def _substitute(response: str, prompt: str) -> str:
    if "{{PROPOSAL_VERSION}}" in response or "{{PROPOSAL_HASH}}" in response:
        version_m = _VERSION_MARKER.search(prompt)
        hash_m = _HASH_MARKER.search(prompt)
        response = response.replace(
            "{{PROPOSAL_VERSION}}", version_m.group(1) if version_m else "0"
        )
        response = response.replace(
            "{{PROPOSAL_HASH}}", hash_m.group(1) if hash_m else ""
        )
    return response


def load_mock_script(path: Path | str) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "responses" in data:
        data = data["responses"]
    if not isinstance(data, list):
        raise ValueError(f"Mock script {path} must be a list (or mapping with 'responses')")
    return data


# ---------------------------------------------------------------------------
# Response builders — used by tests and example-session generators
# ---------------------------------------------------------------------------

def status_response(markdown: str, status: dict[str, Any]) -> str:
    """Compose a well-formed agent response: markdown + one status block."""
    return (
        f"{markdown}\n\n<AI_COUNCIL_STATUS>\n"
        f"{json.dumps(status, indent=2)}\n"
        f"</AI_COUNCIL_STATUS>\n"
    )


def architect_proposal_response(
    proposal_markdown: str,
    decision: str = "PROPOSED",
    confidence: float = 0.9,
    summary: str = "Initial proposal.",
    finding_responses: Optional[list[dict[str, Any]]] = None,
    material_change: bool = True,
    human_questions: Optional[list[str]] = None,
) -> str:
    status = {
        "role": "architect",
        "decision": decision,
        "confidence": confidence,
        "summary": summary,
        "material_change": material_change,
        "finding_responses": finding_responses or [],
        "human_questions": human_questions or [],
    }
    return status_response(proposal_markdown, status)


def architect_agree_response(
    confidence: float = 0.95,
    summary: str = "I agree with the current proposal.",
    finding_responses: Optional[list[dict[str, Any]]] = None,
) -> str:
    status = {
        "role": "architect",
        "decision": "AGREED",
        "proposal_version": "{{PROPOSAL_VERSION}}",
        "proposal_hash": "{{PROPOSAL_HASH}}",
        "confidence": confidence,
        "summary": summary,
        "material_change": False,
        "finding_responses": finding_responses or [],
    }
    # version placeholder must survive as int after substitution
    text = status_response("I agree with the proposal as written.", status)
    return text.replace('"{{PROPOSAL_VERSION}}"', "{{PROPOSAL_VERSION}}")


def reviewer_response(
    decision: str,
    markdown: str = "Review complete.",
    confidence: float = 0.9,
    new_findings: Optional[list[dict[str, Any]]] = None,
    resolved_finding_ids: Optional[list[str]] = None,
    unresolved_blocking_ids: Optional[list[str]] = None,
    version: str = "{{PROPOSAL_VERSION}}",
    hash_: str = "{{PROPOSAL_HASH}}",
) -> str:
    status = {
        "role": "reviewer",
        "decision": decision,
        "proposal_version": version,
        "proposal_hash": hash_,
        "confidence": confidence,
        "summary": markdown[:200],
        "new_findings": new_findings or [],
        "resolved_finding_ids": resolved_finding_ids or [],
        "unresolved_blocking_ids": unresolved_blocking_ids or [],
    }
    text = status_response(markdown, status)
    return text.replace('"{{PROPOSAL_VERSION}}"', "{{PROPOSAL_VERSION}}")


def judge_response(
    decision: str,
    markdown: str = "Independent evaluation complete.",
    confidence: float = 0.9,
    requirement_verdicts: Optional[list[dict[str, Any]]] = None,
    finding_verdicts: Optional[list[dict[str, Any]]] = None,
    new_findings: Optional[list[dict[str, Any]]] = None,
    evidence_requests: Optional[list[dict[str, Any]]] = None,
    approval_statement: str = "",
    version: str = "{{PROPOSAL_VERSION}}",
    hash_: str = "{{PROPOSAL_HASH}}",
) -> str:
    status = {
        "role": "judge",
        "decision": decision,
        "proposal_version": version,
        "proposal_hash": hash_,
        "confidence": confidence,
        "summary": markdown[:200],
        "approval_statement": approval_statement,
        "requirement_verdicts": requirement_verdicts or [],
        "finding_verdicts": finding_verdicts or [],
        "new_findings": new_findings or [],
        "evidence_requests": evidence_requests or [],
    }
    text = status_response(markdown, status)
    return text.replace('"{{PROPOSAL_VERSION}}"', "{{PROPOSAL_VERSION}}")


def extractor_response(
    requirements: list[dict[str, Any]],
    acceptance_criteria: Optional[list[dict[str, Any]]] = None,
) -> str:
    status = {
        "role": "extractor",
        "requirements": requirements,
        "acceptance_criteria": acceptance_criteria or [],
    }
    return status_response("Extracted requirements.", status)
