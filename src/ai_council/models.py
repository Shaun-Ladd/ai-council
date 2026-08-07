"""Core domain models for AI Council.

All structured data exchanged between the orchestrator, agents, and disk is
modeled here with pydantic so it can be validated strictly and exported as
JSON Schema.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

class ArchitectDecision(str, enum.Enum):
    PROPOSED = "PROPOSED"
    REVISED = "REVISED"
    AGREED = "AGREED"
    DISAGREE = "DISAGREE"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class ReviewerDecision(str, enum.Enum):
    APPROVE_FOR_JUDGE = "APPROVE_FOR_JUDGE"
    # Approval contingent on reviewer-authored minor edits; the architect
    # must accept them, then approval binds to the resulting version.
    APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS"
    REVISE = "REVISE"
    DISAGREE = "DISAGREE"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class JudgeDecision(str, enum.Enum):
    APPROVED = "APPROVED"
    REVISE = "REVISE"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Workflow states
# ---------------------------------------------------------------------------

class SessionState(str, enum.Enum):
    INITIALIZING = "INITIALIZING"
    EXTRACTING_REQUIREMENTS = "EXTRACTING_REQUIREMENTS"
    ARCHITECT_PROPOSING = "ARCHITECT_PROPOSING"
    REVIEWER_REVIEWING = "REVIEWER_REVIEWING"
    ARCHITECT_REVISING = "ARCHITECT_REVISING"
    CANDIDATE_CONSENSUS = "CANDIDATE_CONSENSUS"
    JUDGE_EVALUATING = "JUDGE_EVALUATING"
    JUDGE_REJECTED = "JUDGE_REJECTED"
    # implementation phase (implement mode only)
    IMPLEMENTING = "IMPLEMENTING"
    IMPL_REVIEWING = "IMPL_REVIEWING"
    IMPL_REVISING = "IMPL_REVISING"
    IMPL_CONSENSUS = "IMPL_CONSENSUS"
    IMPL_JUDGING = "IMPL_JUDGING"
    IMPL_REJECTED = "IMPL_REJECTED"
    IMPLEMENTED = "IMPLEMENTED"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = {
    SessionState.APPROVED,
    SessionState.IMPLEMENTED,
    SessionState.AWAITING_HUMAN,
    SessionState.BLOCKED,
    SessionState.FAILED,
    SessionState.CANCELLED,
}


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

class RequirementPriority(str, enum.Enum):
    MUST = "MUST"
    SHOULD = "SHOULD"
    COULD = "COULD"


class RequirementStatus(str, enum.Enum):
    OPEN = "OPEN"
    COVERED = "COVERED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RequirementSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str = ""
    section: str = ""


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    source: RequirementSource = Field(default_factory=RequirementSource)
    priority: RequirementPriority = RequirementPriority.MUST
    status: RequirementStatus = RequirementStatus.OPEN
    covered_by: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)


class AcceptanceCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    status: RequirementStatus = RequirementStatus.OPEN
    evidence: list[str] = Field(default_factory=list)


class RequirementsDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_hash: str
    requirements: list[Requirement]
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)

    @field_validator("requirements")
    @classmethod
    def _non_empty(cls, v: list[Requirement]) -> list[Requirement]:
        if not v:
            raise ValueError("requirements must not be empty")
        return v


# ---------------------------------------------------------------------------
# Findings registry
# ---------------------------------------------------------------------------

class FindingSeverity(str, enum.Enum):
    BLOCKING = "BLOCKING"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    ADVISORY = "ADVISORY"


class FindingStatus(str, enum.Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    RESOLVED = "RESOLVED"
    WONT_FIX = "WONT_FIX"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    SUPERSEDED = "SUPERSEDED"


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    detail: str = ""
    severity: FindingSeverity
    status: FindingStatus = FindingStatus.OPEN
    source_role: str = "reviewer"
    cited_section: str = ""
    why_it_matters: str = ""
    acceptance_condition: str = ""
    proposal_version: int = 0
    created_round: int = 0
    judge_cycle: int = 0
    resolution_note: str = ""
    violates: str = ""
    # Set when the finding is reopened or is a re-raise of an existing
    # lineage — used for adaptive architect-model escalation.
    contested: bool = False
    history: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Structured agent status payloads (inside <AI_COUNCIL_STATUS> blocks)
# ---------------------------------------------------------------------------

class NewFinding(BaseModel):
    """A finding as reported by an agent (registry assigns the ID)."""
    model_config = ConfigDict(extra="forbid")
    title: str
    detail: str = ""
    severity: FindingSeverity
    cited_section: str = ""
    why_it_matters: str = ""
    acceptance_condition: str = ""
    # What a BLOCKING finding violates: a requirement/AC id ("REQ-003",
    # "AC-001"), "internal-consistency", or "task-objective". Reviewer
    # BLOCKING findings without this are downgraded to MAJOR.
    violates: str = ""


class FindingResponse(BaseModel):
    """Architect's response to an existing finding."""
    model_config = ConfigDict(extra="forbid")
    finding_id: str
    action: Literal["FIXED", "DEFENDED", "HUMAN_REQUIRED"]
    response: str = ""


class ArchitectStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["architect"] = "architect"
    decision: ArchitectDecision
    proposal_version: int = 0
    proposal_hash: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    summary: str = ""
    material_change: bool = False
    finding_responses: list[FindingResponse] = Field(default_factory=list)
    human_questions: list[str] = Field(default_factory=list)
    unresolved_objections: list[str] = Field(default_factory=list)


class ReviewerStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["reviewer"] = "reviewer"
    decision: ReviewerDecision
    proposal_version: int = 0
    proposal_hash: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    summary: str = ""
    new_findings: list[NewFinding] = Field(default_factory=list)
    resolved_finding_ids: list[str] = Field(default_factory=list)
    reopened_finding_ids: list[str] = Field(default_factory=list)
    unresolved_blocking_ids: list[str] = Field(default_factory=list)
    # APPROVE_WITH_CONDITIONS only: the reviewer's required minor edits as
    # SEARCH/REPLACE blocks against the reviewed proposal.
    condition_edits: str = ""
    human_questions: list[str] = Field(default_factory=list)


class RequirementVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: str
    verdict: Literal["ADDRESSED", "NOT_ADDRESSED", "PARTIAL", "UNCLEAR"]
    notes: str = ""


class FindingVerdict(BaseModel):
    """Judge arbitration ruling on a single open finding."""
    model_config = ConfigDict(extra="forbid")
    finding_id: str
    verdict: Literal["UPHELD", "OVERRULED"]
    notes: str = ""


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    type: str = "other"
    related_requirement_ids: list[str] = Field(default_factory=list)


class JudgeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["judge"] = "judge"
    decision: JudgeDecision
    proposal_version: int = 0
    proposal_hash: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    summary: str = ""
    approval_statement: str = ""
    requirement_verdicts: list[RequirementVerdict] = Field(default_factory=list)
    finding_verdicts: list[FindingVerdict] = Field(default_factory=list)
    new_findings: list[NewFinding] = Field(default_factory=list)
    reopened_finding_ids: list[str] = Field(default_factory=list)
    evidence_requests: list[EvidenceRequest] = Field(default_factory=list)
    human_questions: list[str] = Field(default_factory=list)


AgentStatus = Union[ArchitectStatus, ReviewerStatus, JudgeStatus]

STATUS_MODEL_BY_ROLE: dict[str, type[BaseModel]] = {
    "architect": ArchitectStatus,
    "reviewer": ReviewerStatus,
    "judge": JudgeStatus,
}


class ExtractionStatus(BaseModel):
    """Structured payload returned by the requirement-extractor invocation."""
    model_config = ConfigDict(extra="forbid")
    role: Literal["extractor"] = "extractor"
    requirements: list[Requirement]
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: str
    created_at: str = Field(default_factory=utcnow_iso)
    command: str = ""
    exit_code: Optional[int] = None
    artifact_path: str = ""
    sha256: str = ""
    description: str = ""


# ---------------------------------------------------------------------------
# Transcript events
# ---------------------------------------------------------------------------

class TranscriptEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    timestamp: str = Field(default_factory=utcnow_iso)
    session_id: str
    round: int = 0
    judge_cycle: int = 0
    agent: str = ""
    role: str = ""
    kind: str = "agent_response"  # agent_response | state_change | note | error
    invocation_id: str = ""
    prompt_name: str = ""
    prompt_hash: str = ""
    proposal_version: int = 0
    proposal_hash: str = ""
    response_path: str = ""
    parsed_decision: str = ""
    duration_seconds: float = 0.0
    exit_code: Optional[int] = None
    retry_count: int = 0
    usage: dict[str, Any] = Field(default_factory=dict)
    detail: str = ""


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

class ProposalRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    sha256: str
    path: str
    created_at: str = Field(default_factory=utcnow_iso)


class InvocationCheckpoint(BaseModel):
    """A completed agent invocation, recorded so resume can skip re-running it."""
    model_config = ConfigDict(extra="forbid")
    invocation_id: str
    role: str
    agent: str
    purpose: str
    round: int = 0
    judge_cycle: int = 0
    response_path: str = ""
    status_json: dict[str, Any] = Field(default_factory=dict)
    decision: str = ""
    completed_at: str = Field(default_factory=utcnow_iso)


class SessionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: str = ""  # APPROVED | REVISE | HUMAN_REQUIRED | BLOCKED | FAILED | CANCELLED
    reason: str = ""
    report_path: str = ""


class SessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    task_file: str = ""
    task_hash: str = ""
    state: SessionState = SessionState.INITIALIZING
    round: int = 0
    judge_cycle: int = 0
    proposals: list[ProposalRef] = Field(default_factory=list)
    invocations: list[InvocationCheckpoint] = Field(default_factory=list)
    agent_failures: dict[str, int] = Field(default_factory=dict)
    disagreement_counts: dict[str, int] = Field(default_factory=dict)
    seen_proposal_hashes: list[str] = Field(default_factory=list)
    churn_points: int = 0
    arbitration_used: bool = False
    round_extension: int = 0
    # approve-with-conditions state: reviewer edits awaiting architect
    # acceptance, and the binding of a conditional approval to the version
    # the orchestrator assembled from those edits.
    pending_conditions: dict[str, Any] = Field(default_factory=dict)
    conditional_binding: dict[str, Any] = Field(default_factory=dict)
    # implementation phase
    implement_mode: bool = False
    worktree: str = ""
    worktree_branch: str = ""
    implementations: list[ProposalRef] = Field(default_factory=list)
    seen_impl_hashes: list[str] = Field(default_factory=list)
    impl_round: int = 0
    impl_judge_cycle: int = 0

    @property
    def latest_implementation(self) -> Optional[ProposalRef]:
        return self.implementations[-1] if self.implementations else None
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    outcome: SessionOutcome = Field(default_factory=SessionOutcome)

    @property
    def latest_proposal(self) -> Optional[ProposalRef]:
        return self.proposals[-1] if self.proposals else None

    def find_invocation(self, invocation_id: str) -> Optional[InvocationCheckpoint]:
        for inv in self.invocations:
            if inv.invocation_id == invocation_id:
                return inv
        return None
