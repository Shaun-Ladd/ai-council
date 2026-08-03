"""The AI Council orchestrator.

Drives the explicit workflow state machine:

    INITIALIZING -> EXTRACTING_REQUIREMENTS -> ARCHITECT_PROPOSING
    -> REVIEWER_REVIEWING <-> ARCHITECT_REVISING
    -> CANDIDATE_CONSENSUS -> JUDGE_EVALUATING
    -> APPROVED | JUDGE_REJECTED | AWAITING_HUMAN | BLOCKED | FAILED

All agent interaction goes through role-bound adapters; all artifacts are
immutable; state is persisted after every transition so interrupted sessions
can be resumed without repeating completed agent calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel

from .adapters import AgentAdapter, AgentAdapterError, InvocationRequest, create_adapter
from .adapters.process import ProcessCancelled
from .config import AgentConfig, CouncilConfig
from .consensus import ConsensusResult, check_candidate_consensus
from .evidence import EvidenceStore
from .hashing import sha256_text
from .loopguard import (
    LoopEscalation,
    check_judge_cycle_limit,
    check_new_proposal_hash,
    check_round_limit,
    note_disagreement,
    review_churn_signal,
)
from .models import (
    ArchitectDecision,
    ArchitectStatus,
    ExtractionStatus,
    FindingSeverity,
    JudgeDecision,
    JudgeStatus,
    NewFinding,
    ProposalRef,
    InvocationCheckpoint,
    RequirementPriority,
    RequirementsDoc,
    ReviewerDecision,
    ReviewerStatus,
    SessionRecord,
    SessionState,
    TranscriptEvent,
    utcnow_iso,
)
from .parsing import StatusParseError, parse_status, strip_status_block
from .prompts import PromptLibrary
from .redaction import redact
from .registry import FindingLifecycleError, FindingsRegistry
from .reporting import write_reports
from .statemachine import is_terminal, validate_transition
from .storage import SessionStore, atomic_write_json, new_session_id, write_immutable
from .transcript import Transcript


class Escalation(Exception):
    """Move the session to a terminal state with a reason."""

    def __init__(self, state: SessionState, reason: str):
        super().__init__(reason)
        self.state = state
        self.reason = reason


class Orchestrator:
    def __init__(
        self,
        *,
        config: CouncilConfig,
        store: SessionStore,
        record: SessionRecord,
        task_text: str,
        printer: Optional[Callable[[str], None]] = None,
        echo_responses: bool = False,
    ):
        self.config = config
        self.store = store
        self.record = record
        self.task_text = task_text
        self.printer = printer or (lambda msg: None)
        self.echo_responses = echo_responses
        self.transcript = Transcript(store)
        self.registry = FindingsRegistry.load(store.findings_json)
        self.evidence = EvidenceStore(store)
        self.prompts = PromptLibrary(override_dir=store.council_root / "prompts")
        self.requirements: Optional[RequirementsDoc] = None
        if store.requirements_json.is_file():
            self.requirements = RequirementsDoc.model_validate(
                json.loads(store.requirements_json.read_text(encoding="utf-8"))
            )
        self._adapters: dict[str, AgentAdapter] = {}
        self.last_architect: Optional[ArchitectStatus] = None
        self.last_reviewer: Optional[ReviewerStatus] = None
        self.last_judge: Optional[JudgeStatus] = None
        self._rebuild_statuses_from_checkpoints()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def new_session(
        cls,
        task_path: Path | str,
        config: CouncilConfig,
        repo_root: Path | str = ".",
        printer: Optional[Callable[[str], None]] = None,
        echo_responses: bool = False,
    ) -> "Orchestrator":
        task_path = Path(task_path)
        task_text = task_path.read_text(encoding="utf-8")
        council_root = Path(repo_root) / ".ai-council"
        session_id = new_session_id()
        store = SessionStore(council_root, session_id)
        store.create_layout()
        record = SessionRecord(
            id=session_id,
            task_file=str(task_path),
            task_hash=sha256_text(task_text),
            config_snapshot=config.model_dump(mode="json"),
        )
        store.save_session(record)
        write_immutable(store.problem_md, task_text)
        return cls(config=config, store=store, record=record, task_text=task_text,
                   printer=printer, echo_responses=echo_responses)

    @classmethod
    def resume_session(
        cls,
        store: SessionStore,
        config: Optional[CouncilConfig] = None,
        printer: Optional[Callable[[str], None]] = None,
        echo_responses: bool = False,
    ) -> "Orchestrator":
        record = store.load_session()
        if config is None:
            config = CouncilConfig.model_validate(record.config_snapshot)
        if not config.session.resumable:
            raise Escalation(SessionState.FAILED, "Session is not resumable (session.resumable=false)")
        task_text = store.problem_md.read_text(encoding="utf-8")
        return cls(config=config, store=store, record=record, task_text=task_text,
                   printer=printer, echo_responses=echo_responses)

    # ------------------------------------------------------------------
    # Adapters
    # ------------------------------------------------------------------
    def _agent_config(self, role: str) -> AgentConfig:
        agents = self.config.agents
        if role == "extractor":
            return agents.extractor or agents.architect
        return getattr(agents, role)

    def adapter_for(self, role: str) -> AgentAdapter:
        if role not in self._adapters:
            self._adapters[role] = create_adapter(self._agent_config(role), self.config.security)
        return self._adapters[role]

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self) -> SessionRecord:
        handlers = {
            SessionState.INITIALIZING: self._h_initializing,
            SessionState.EXTRACTING_REQUIREMENTS: self._h_extracting,
            SessionState.ARCHITECT_PROPOSING: self._h_proposing,
            SessionState.REVIEWER_REVIEWING: self._h_reviewing,
            SessionState.ARCHITECT_REVISING: self._h_revising,
            SessionState.CANDIDATE_CONSENSUS: self._h_consensus,
            SessionState.JUDGE_EVALUATING: self._h_judging,
            SessionState.JUDGE_REJECTED: self._h_judge_rejected,
        }
        try:
            while not is_terminal(self.record.state):
                handlers[self.record.state]()
        except (Escalation, LoopEscalation) as esc:
            state = esc.state if isinstance(esc, Escalation) else SessionState(esc.target)
            self._finalize(state, esc.reason)
        except (ProcessCancelled, KeyboardInterrupt):
            self._finalize(SessionState.CANCELLED, "Session cancelled by user interrupt.")
        except AgentAdapterError as exc:
            self._finalize(SessionState.FAILED, f"Agent adapter error: {exc}")
        else:
            if self.record.state == SessionState.APPROVED:
                self._finalize(SessionState.APPROVED, self.record.outcome.reason or "Approved by Judge.")
        return self.record

    def _finalize(self, state: SessionState, reason: str) -> None:
        if self.record.state != state:
            validate_transition(self.record.state, state)
            self.record.state = state
        self.record.outcome.result = state.value
        self.record.outcome.reason = reason
        self._save_registry()
        self.store.save_session(self.record)
        self.transcript.note(
            self.record.id, reason, kind="state_change",
            round_no=self.record.round, judge_cycle=self.record.judge_cycle,
            parsed_decision=state.value,
        )
        write_reports(
            store=self.store,
            record=self.record,
            registry=self.registry,
            requirements=self.requirements,
            last_judge=self.last_judge,
            evidence=self.evidence,
        )
        self.printer(f"[{state.value}] {reason}")

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------
    def _h_initializing(self) -> None:
        self._decision_note("Session initialized.")
        self._transition(SessionState.EXTRACTING_REQUIREMENTS)

    def _h_extracting(self) -> None:
        if self.requirements is None:
            status, _, _ = self._invoke(
                role="extractor",
                purpose="extract",
                prompt_name="requirement-extractor.md",
                context={"task_text": self.task_text, "task_file": self.record.task_file},
                status_model=ExtractionStatus,
            )
            assert isinstance(status, ExtractionStatus)
            self.requirements = RequirementsDoc(
                task_hash=self.record.task_hash,
                requirements=status.requirements,
                acceptance_criteria=status.acceptance_criteria,
            )
            write_immutable(
                self.store.requirements_json,
                json.dumps(self.requirements.model_dump(mode="json"), indent=2) + "\n",
            )
            self.evidence.add(
                type="traceability",
                content=self.store.requirements_json.read_text(encoding="utf-8"),
                description=f"Normalized requirements extracted from {self.record.task_file}",
            )
            self._decision_note(
                f"Extracted {len(self.requirements.requirements)} requirements and "
                f"{len(self.requirements.acceptance_criteria)} acceptance criteria."
            )
        self._transition(SessionState.ARCHITECT_PROPOSING)

    def _h_proposing(self) -> None:
        status, response_text, _ = self._invoke(
            role="architect",
            purpose="propose",
            prompt_name="architect-initial.md",
            context={
                "task_text": self.task_text,
                "requirements_markdown": self._requirements_markdown(),
            },
            status_model=ArchitectStatus,
        )
        assert isinstance(status, ArchitectStatus)
        self.last_architect = status
        self._check_common_escalations("architect", status.decision.value,
                                       status.human_questions, status.summary)
        if status.decision != ArchitectDecision.PROPOSED:
            raise Escalation(
                SessionState.FAILED,
                f"Architect returned unexpected decision {status.decision.value} for initial proposal.",
            )
        self._store_new_proposal(strip_status_block(response_text), revision_requested=False)
        self._next_review_round()

    def _h_reviewing(self) -> None:
        proposal = self._current_proposal()
        prior_open_count = len(self.registry.open_findings())
        status, response_text, _ = self._invoke(
            role="reviewer",
            purpose="review",
            prompt_name="reviewer.md",
            context={
                "task_text": self.task_text,
                "requirements_markdown": self._requirements_markdown(),
                "proposal_text": self._proposal_text(),
                "proposal_version": proposal.version,
                "proposal_hash": proposal.sha256,
                "findings_markdown": self.registry.to_markdown(),
                "architect_responses_markdown": self._architect_responses_markdown(),
                "arbitration_rulings_markdown": self._arbitration_rulings_markdown(),
                "human_guidance": self._human_guidance(),
            },
            status_model=ReviewerStatus,
            expect_version=proposal.version,
            expect_hash=proposal.sha256,
        )
        assert isinstance(status, ReviewerStatus)
        self.last_reviewer = status

        review_path = self.store.review_path(proposal.version, self.record.round)
        if not review_path.exists():
            write_immutable(review_path, redact(response_text))

        added = self.registry.add_new(
            status.new_findings, source_role="reviewer",
            proposal_version=proposal.version, round_no=self.record.round,
            judge_cycle=self.record.judge_cycle,
        )
        self._safe_resolve(status.resolved_finding_ids, by_role="reviewer")
        self.registry.reopen(status.reopened_finding_ids, by_role="reviewer")
        self._save_registry()
        self._decision_note(
            f"Round {self.record.round}: reviewer decision {status.decision.value} "
            f"({len(added)} new findings, {len(status.resolved_finding_ids)} marked resolved)."
        )

        churn = review_churn_signal(
            added=added,
            resolved_ids=status.resolved_finding_ids,
            reopened_ids=status.reopened_finding_ids,
            decision=status.decision.value,
            prior_open_count=prior_open_count,
            registry=self.registry,
        )
        if churn:
            self.record.churn_points += 1
            self.store.save_session(self.record)
            self.transcript.note(
                self.record.id,
                f"Reviewer churn signal ({self.record.churn_points}/"
                f"{self.config.session.reviewerChurnLimit}): {churn}",
                kind="note", round_no=self.record.round,
                judge_cycle=self.record.judge_cycle, role="reviewer",
            )
            if self.record.churn_points >= self.config.session.reviewerChurnLimit:
                self._run_arbitration(f"reviewer churn: {churn}", on_unavailable="AWAITING_HUMAN")

        self._check_common_escalations("reviewer", status.decision.value,
                                       status.human_questions, status.summary)
        if status.decision == ReviewerDecision.APPROVE_FOR_JUDGE:
            self._transition(SessionState.CANDIDATE_CONSENSUS)
        elif status.decision == ReviewerDecision.DISAGREE:
            note_disagreement(
                self.record, self.config.session,
                (self.last_architect.decision.value if self.last_architect else "?"),
                status.decision.value, self.registry,
            )
            self._transition(SessionState.ARCHITECT_REVISING)
        else:  # REVISE
            self._transition(SessionState.ARCHITECT_REVISING)

    def _h_revising(self) -> None:
        proposal = self._current_proposal()
        status, response_text, _ = self._invoke(
            role="architect",
            purpose="revise",
            prompt_name="architect-revision.md",
            context={
                "task_text": self.task_text,
                "requirements_markdown": self._requirements_markdown(),
                "proposal_text": self._proposal_text(),
                "proposal_version": proposal.version,
                "proposal_hash": proposal.sha256,
                "open_findings_markdown": self._open_findings_markdown(),
                "review_text": self._latest_artifact_text(self.store.reviews_dir),
                "judgment_text": self._latest_artifact_text(self.store.judgments_dir)
                if self.record.judge_cycle > 0 else "",
                "human_guidance": self._human_guidance(),
            },
            status_model=ArchitectStatus,
        )
        assert isinstance(status, ArchitectStatus)
        self.last_architect = status
        self._apply_architect_finding_responses(status)
        self._check_common_escalations("architect", status.decision.value,
                                       status.human_questions, status.summary)

        if status.decision == ArchitectDecision.REVISED:
            self._store_new_proposal(strip_status_block(response_text), revision_requested=True)
        elif status.decision in (ArchitectDecision.AGREED, ArchitectDecision.DISAGREE):
            self._verify_echo("architect", status.proposal_version, status.proposal_hash, proposal)
            if status.decision == ArchitectDecision.DISAGREE:
                note_disagreement(
                    self.record, self.config.session, status.decision.value,
                    (self.last_reviewer.decision.value if self.last_reviewer else "?"),
                    self.registry,
                )
        else:
            raise Escalation(
                SessionState.FAILED,
                f"Architect returned unexpected decision {status.decision.value} during revision.",
            )
        self._decision_note(
            f"Round {self.record.round}: architect decision {status.decision.value} "
            f"(material_change={status.material_change})."
        )
        self._next_review_round()

    def _h_consensus(self) -> None:
        proposal = self._current_proposal()
        # The architect must explicitly agree to the exact reviewed version.
        needs_confirmation = not (
            self.last_architect is not None
            and self.last_architect.decision == ArchitectDecision.AGREED
            and self.last_architect.proposal_version == proposal.version
            and self.last_architect.proposal_hash == proposal.sha256
        )
        if needs_confirmation:
            status, _, _ = self._invoke(
                role="architect",
                purpose="confirm",
                prompt_name="architect-confirm.md",
                context={
                    "proposal_text": self._proposal_text(),
                    "proposal_version": proposal.version,
                    "proposal_hash": proposal.sha256,
                    "review_text": self._latest_artifact_text(self.store.reviews_dir),
                },
                status_model=ArchitectStatus,
                expect_version=proposal.version,
                expect_hash=proposal.sha256,
            )
            assert isinstance(status, ArchitectStatus)
            self.last_architect = status
            self._check_common_escalations("architect", status.decision.value,
                                           status.human_questions, status.summary)

        result = self._consensus_result()
        self.transcript.note(
            self.record.id, result.summary(), kind="note",
            round_no=self.record.round, judge_cycle=self.record.judge_cycle,
            parsed_decision="CONSENSUS" if result.ok else "NO_CONSENSUS",
        )
        self._decision_note(result.summary())
        if result.ok:
            check_judge_cycle_limit(self.record, self.config.session)
            self.record.judge_cycle += 1
            self._transition(SessionState.JUDGE_EVALUATING)
        else:
            if (
                self.last_architect is not None
                and self.last_architect.decision == ArchitectDecision.DISAGREE
            ):
                note_disagreement(
                    self.record, self.config.session,
                    self.last_architect.decision.value,
                    (self.last_reviewer.decision.value if self.last_reviewer else "?"),
                    self.registry,
                )
            self._consensus_failure_reasons = result.reasons
            self._transition(SessionState.ARCHITECT_REVISING)

    def _h_judging(self) -> None:
        proposal = self._current_proposal()
        status, response_text, _ = self._invoke(
            role="judge",
            purpose="judge",
            prompt_name="judge.md",
            context={
                "task_text": self.task_text,
                "requirements_markdown": self._requirements_markdown(),
                "proposal_text": self._proposal_text(),
                "proposal_version": proposal.version,
                "proposal_hash": proposal.sha256,
                "review_text": self._latest_artifact_text(self.store.reviews_dir),
                "findings_markdown": self.registry.to_markdown(),
                "decisions_log": self._decisions_log_text(),
                "evidence_markdown": self.evidence.summary_markdown(),
                "consensus_summary": self._consensus_result().summary(),
            },
            status_model=JudgeStatus,
            expect_version=proposal.version,
            expect_hash=proposal.sha256,
        )
        assert isinstance(status, JudgeStatus)
        self.last_judge = status

        judgment_path = self.store.judgment_path(proposal.version, self.record.judge_cycle)
        if not judgment_path.exists():
            write_immutable(judgment_path, redact(response_text))
        self._decision_note(
            f"Judge cycle {self.record.judge_cycle}: decision {status.decision.value}."
        )
        self._check_common_escalations("judge", status.decision.value,
                                       status.human_questions, status.summary)

        if status.decision == JudgeDecision.APPROVED:
            self._validate_judge_approval(status, proposal)
            self.record.outcome.reason = (
                f"Approved by Judge: proposal v{proposal.version:03d} "
                f"(sha256 {proposal.sha256})."
            )
            self._transition(SessionState.APPROVED)
            return

        if status.decision in (JudgeDecision.REVISE, JudgeDecision.EVIDENCE_REQUIRED):
            self.registry.add_new(
                status.new_findings, source_role="judge",
                proposal_version=proposal.version, round_no=self.record.round,
                judge_cycle=self.record.judge_cycle,
            )
            evidence_findings = [
                NewFinding(
                    title=f"Evidence required: {req.description}",
                    detail=(
                        f"The Judge requires evidence of type '{req.type}'"
                        + (f" for {', '.join(req.related_requirement_ids)}"
                           if req.related_requirement_ids else "")
                    ),
                    severity=FindingSeverity.BLOCKING,
                    why_it_matters="Approval is withheld until this evidence exists.",
                    acceptance_condition="Provide the requested evidence artifact.",
                )
                for req in status.evidence_requests
            ]
            if evidence_findings:
                self.registry.add_new(
                    evidence_findings, source_role="judge",
                    proposal_version=proposal.version, round_no=self.record.round,
                    judge_cycle=self.record.judge_cycle,
                )
            self.registry.reopen(status.reopened_finding_ids, by_role="judge")
            self._save_registry()
            self._transition(SessionState.JUDGE_REJECTED)
            return

        raise Escalation(
            SessionState.FAILED,
            f"Judge returned unexpected decision {status.decision.value}.",
        )

    def _h_judge_rejected(self) -> None:
        self._decision_note(
            f"Judge rejected the candidate (cycle {self.record.judge_cycle}); "
            "routing findings back to the architect."
        )
        self._transition(SessionState.ARCHITECT_REVISING)

    # ------------------------------------------------------------------
    # Agent invocation with checkpointing, retries, and format repair
    # ------------------------------------------------------------------
    def _invoke(
        self,
        *,
        role: str,
        purpose: str,
        prompt_name: str,
        context: dict[str, Any],
        status_model: type[BaseModel],
        expect_version: Optional[int] = None,
        expect_hash: Optional[str] = None,
    ) -> tuple[BaseModel, str, str]:
        invocation_id = f"{purpose}-r{self.record.round:03d}-j{self.record.judge_cycle:02d}-{role}"
        checkpoint = self.record.find_invocation(invocation_id)
        if checkpoint is not None:
            status = status_model.model_validate(checkpoint.status_json)
            response_text = ""
            if checkpoint.response_path and Path(checkpoint.response_path).is_file():
                response_text = Path(checkpoint.response_path).read_text(encoding="utf-8")
            self.printer(f"[resume] skipping completed invocation {invocation_id}")
            return status, response_text, checkpoint.response_path

        adapter = self.adapter_for(role)
        agent_config = self._agent_config(role)
        limits = self.config.session
        prompt = self.prompts.render(prompt_name, **context)
        prompt_text = prompt.text
        read_only = self.config.workspace.mode == "read-only"

        failures = 0
        format_retries = 0
        attempt = 0
        last_error = ""
        max_attempts = limits.maxAgentFailures + limits.maxFormatRetries + 2

        while attempt < max_attempts:
            attempt += 1
            request = InvocationRequest(
                prompt=prompt_text,
                invocation_id=f"{invocation_id}-a{attempt}",
                role=role,
                purpose=purpose,
                timeout_seconds=agent_config.timeoutSeconds,
                cwd=self._workspace_cwd(),
                read_only=read_only,
            )
            result = adapter.invoke(request)
            self._write_raw_logs(request.invocation_id, result.stdout, result.stderr)

            if not result.ok:
                failures += 1
                self.record.agent_failures[role] = self.record.agent_failures.get(role, 0) + 1
                reason = "timed out" if result.timed_out else f"exited with code {result.exit_code}"
                self.transcript.note(
                    self.record.id,
                    f"Agent {role} invocation {request.invocation_id} {reason}.",
                    kind="error", round_no=self.record.round,
                    judge_cycle=self.record.judge_cycle, role=role, agent=adapter.name,
                )
                self.store.save_session(self.record)
                if failures > limits.maxAgentFailures:
                    raise Escalation(
                        SessionState.FAILED,
                        f"Agent '{role}' failed {failures} times "
                        f"(last: {reason}). Limit is {limits.maxAgentFailures} retries.",
                    )
                continue

            try:
                status = parse_status(result.stdout, status_model)
            except StatusParseError as exc:
                format_retries += 1
                last_error = f"{exc} {exc.detail}".strip()
                self.transcript.note(
                    self.record.id,
                    f"Invalid structured output from {role} "
                    f"({request.invocation_id}): {exc}",
                    kind="error", round_no=self.record.round,
                    judge_cycle=self.record.judge_cycle, role=role, agent=adapter.name,
                )
                if format_retries > limits.maxFormatRetries:
                    raise Escalation(
                        SessionState.FAILED,
                        f"Structured output from '{role}' failed validation "
                        f"{format_retries} times; giving up. Last error: {exc}",
                    )
                proposal = self.record.latest_proposal
                prompt_repair = self.prompts.render(
                    "format-repair.md",
                    role=role if role != "extractor" else "extractor",
                    validation_error=last_error[:4000],
                    previous_response=result.stdout[-20000:],
                    proposal_version=expect_version
                    if expect_version is not None
                    else (proposal.version if proposal else 0),
                    proposal_hash=expect_hash
                    if expect_hash is not None
                    else (proposal.sha256 if proposal else ""),
                )
                prompt_text = prompt_repair.text
                continue

            decision = str(getattr(status, "decision", ""))
            decision_value = getattr(getattr(status, "decision", None), "value", decision)
            if decision_value == "ERROR":
                failures += 1
                self.record.agent_failures[role] = self.record.agent_failures.get(role, 0) + 1
                self.store.save_session(self.record)
                if failures > limits.maxAgentFailures:
                    raise Escalation(
                        SessionState.FAILED,
                        f"Agent '{role}' reported ERROR {failures} times.",
                    )
                prompt_text = prompt.text  # retry the original prompt
                continue

            if expect_version is not None and expect_hash is not None:
                v = getattr(status, "proposal_version", None)
                h = getattr(status, "proposal_hash", None)
                if v != expect_version or h != expect_hash:
                    failures += 1
                    self.transcript.note(
                        self.record.id,
                        f"Agent {role} referenced proposal v{v} hash "
                        f"{str(h)[:12]}…, expected v{expect_version} hash "
                        f"{expect_hash[:12]}…. Discarding response.",
                        kind="error", round_no=self.record.round,
                        judge_cycle=self.record.judge_cycle, role=role, agent=adapter.name,
                    )
                    if failures > limits.maxAgentFailures:
                        raise Escalation(
                            SessionState.FAILED,
                            f"Agent '{role}' repeatedly referenced a stale proposal "
                            f"version or hash (expected v{expect_version}, "
                            f"hash {expect_hash[:12]}…).",
                        )
                    prompt_text = prompt.text
                    continue

            # Success: persist response, checkpoint, transcript event.
            response_path = self.store.logs_dir / f"{invocation_id}.response.md"
            response_redacted = redact(result.stdout)
            if not response_path.exists():
                write_immutable(response_path, response_redacted)
            proposal = self.record.latest_proposal
            event = TranscriptEvent(
                event_id=self.transcript.next_event_id(),
                session_id=self.record.id,
                round=self.record.round,
                judge_cycle=self.record.judge_cycle,
                agent=adapter.name,
                role=role,
                kind="agent_response",
                invocation_id=invocation_id,
                prompt_name=prompt.name,
                prompt_hash=prompt.sha256,
                proposal_version=proposal.version if proposal else 0,
                proposal_hash=proposal.sha256 if proposal else "",
                response_path=str(response_path),
                parsed_decision=decision_value,
                duration_seconds=result.duration_seconds,
                exit_code=result.exit_code,
                retry_count=attempt - 1,
                usage=result.usage,
            )
            self.transcript.record(event)
            self.record.invocations.append(
                InvocationCheckpoint(
                    invocation_id=invocation_id,
                    role=role,
                    agent=adapter.name,
                    purpose=purpose,
                    round=self.record.round,
                    judge_cycle=self.record.judge_cycle,
                    response_path=str(response_path),
                    status_json=status.model_dump(mode="json"),
                    decision=decision_value,
                )
            )
            self.store.save_session(self.record)
            self.printer(f"[{role}] {purpose} -> {decision_value or 'ok'}")
            summary = getattr(status, "summary", "")
            if summary:
                self.printer(f"    {summary}")
            if self.echo_responses:
                self.printer(response_redacted)
            return status, response_redacted, str(response_path)

        raise Escalation(
            SessionState.FAILED,
            f"Agent '{role}' exhausted {max_attempts} attempts. Last error: {last_error}",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _transition(self, target: SessionState) -> None:
        validate_transition(self.record.state, target)
        previous = self.record.state
        self.record.state = target
        self.store.save_session(self.record)
        self.transcript.note(
            self.record.id, f"{previous.value} -> {target.value}",
            kind="state_change", round_no=self.record.round,
            judge_cycle=self.record.judge_cycle,
        )
        self.printer(f"[state] {previous.value} -> {target.value}")

    def _next_review_round(self) -> None:
        try:
            check_round_limit(self.record, self.config.session)
        except LoopEscalation as esc:
            # Deadlock at the round limit: give the Judge one chance to
            # arbitrate before blocking the session.
            self._run_arbitration(esc.reason, on_unavailable="BLOCKED")
            check_round_limit(self.record, self.config.session)
        self.record.round += 1
        self._transition(SessionState.REVIEWER_REVIEWING)

    def _run_arbitration(self, trigger_reason: str, *, on_unavailable: str) -> None:
        """One-time Judge arbitration of a deadlocked debate.

        The Judge rules UPHELD/OVERRULED on every open finding. Overruled
        findings are superseded (binding on the reviewer); the debate gains
        ``arbitrationBonusRounds``. The Judge cannot approve here — approval
        still requires consensus plus a normal Judge evaluation.
        """
        limits = self.config.session
        if not limits.judgeArbitration or self.record.arbitration_used:
            why = ("already arbitrated once" if self.record.arbitration_used
                   else "arbitration disabled")
            raise LoopEscalation(
                on_unavailable,
                f"Debate deadlocked ({trigger_reason}); Judge arbitration "
                f"unavailable ({why}). Human intervention is the remaining path.",
            )
        proposal = self._current_proposal()
        open_before = self.registry.open_findings()
        self._decision_note(f"Judge arbitration triggered: {trigger_reason}")
        status, response_text, _ = self._invoke(
            role="judge",
            purpose="arbitrate",
            prompt_name="judge-arbitration.md",
            context={
                "trigger_reason": trigger_reason,
                "task_text": self.task_text,
                "requirements_markdown": self._requirements_markdown(),
                "proposal_text": self._proposal_text(),
                "proposal_version": proposal.version,
                "proposal_hash": proposal.sha256,
                "open_findings_markdown": self._open_findings_with_responses_markdown(),
                "debate_summary": (
                    f"{self.record.round} debate rounds, "
                    f"{len(self.record.proposals)} proposal versions, "
                    f"{len(self.registry.findings)} findings raised, "
                    f"{len(open_before)} still open."
                ),
            },
            status_model=JudgeStatus,
            expect_version=proposal.version,
            expect_hash=proposal.sha256,
        )
        assert isinstance(status, JudgeStatus)

        arb_path = self.store.judgments_dir / (
            f"arbitration-v{proposal.version:03d}-r{self.record.round:03d}.md"
        )
        if not arb_path.exists():
            write_immutable(arb_path, redact(response_text))

        self._check_common_escalations("judge", status.decision.value,
                                       status.human_questions, status.summary)
        if status.decision not in (JudgeDecision.REVISE, JudgeDecision.APPROVED):
            raise Escalation(
                SessionState.FAILED,
                f"Judge returned unexpected arbitration decision {status.decision.value}.",
            )

        overruled = [v.finding_id for v in status.finding_verdicts
                     if v.verdict == "OVERRULED"]
        notes = {v.finding_id: v.notes for v in status.finding_verdicts}
        if status.decision == JudgeDecision.APPROVED and not status.finding_verdicts:
            # An arbitration cannot approve; treat a bare APPROVED as
            # "no open finding survives scrutiny".
            overruled = [f.id for f in open_before]
        superseded = self.registry.supersede(
            overruled, by_role="judge",
            note="Judge arbitration: overruled as disproportionate to task scope",
        )
        for fid in superseded:
            if notes.get(fid):
                self.registry.get(fid).resolution_note = f"Judge arbitration: {notes[fid]}"
        upheld = [f.id for f in self.registry.open_findings()]
        self.record.arbitration_used = True
        self.record.churn_points = 0
        self.record.round_extension += limits.arbitrationBonusRounds
        self._save_registry()
        self.store.save_session(self.record)
        summary = (
            f"Arbitration: {len(superseded)} finding(s) overruled "
            f"({', '.join(superseded) or 'none'}), {len(upheld)} upheld "
            f"({', '.join(upheld) or 'none'}); debate extended by "
            f"{limits.arbitrationBonusRounds} rounds."
        )
        self._decision_note(summary)
        self.transcript.note(
            self.record.id, summary, kind="note",
            round_no=self.record.round, judge_cycle=self.record.judge_cycle,
            role="judge", parsed_decision="ARBITRATED",
        )
        self._arbitration_note = summary + f" Judge reasoning: {status.summary}"

    def _human_guidance(self) -> str:
        if self.store.human_guidance_md.is_file():
            return self.store.human_guidance_md.read_text(encoding="utf-8")
        return ""

    def _arbitration_rulings_markdown(self) -> str:
        rulings = [
            f"- **{f.id}** [{f.severity.value}] {f.title} — OVERRULED"
            + (f" ({f.resolution_note})" if f.resolution_note else "")
            for f in self.registry.findings
            if f.status.value == "SUPERSEDED"
            and f.resolution_note.startswith("Judge arbitration")
        ]
        return "\n".join(rulings)

    def _open_findings_with_responses_markdown(self) -> str:
        parts = [self.registry.to_markdown(only_open=True)]
        responses = self._architect_responses_markdown()
        if responses:
            parts.append("\n**Architect's latest responses to findings:**\n" + responses)
        return "\n".join(parts)

    def _workspace_cwd(self) -> Path:
        """Agent working directory: workspace.root resolved against the
        session's repository root (never against the orchestrator process's
        own cwd, which may be an unrelated directory)."""
        root = Path(self.config.workspace.root)
        if not root.is_absolute():
            root = self.store.council_root.parent / root
        return root.resolve()

    def _current_proposal(self) -> ProposalRef:
        proposal = self.record.latest_proposal
        if proposal is None:
            raise Escalation(SessionState.FAILED, "No proposal exists in this session.")
        return proposal

    def _proposal_text(self) -> str:
        return Path(self._current_proposal().path).read_text(encoding="utf-8")

    def _store_new_proposal(self, body: str, *, revision_requested: bool) -> None:
        body = body.strip() + "\n"
        new_hash = sha256_text(body)
        previous = self.record.latest_proposal
        check_new_proposal_hash(
            self.record, new_hash,
            revision_requested=revision_requested,
            previous_hash=previous.sha256 if previous else None,
        )
        version = (previous.version if previous else 0) + 1
        path = self.store.proposal_path(version)
        write_immutable(path, body)
        self.record.proposals.append(
            ProposalRef(version=version, sha256=new_hash, path=str(path))
        )
        self.record.seen_proposal_hashes.append(new_hash)
        self.store.save_session(self.record)
        self._decision_note(f"Proposal v{version:03d} created (sha256 {new_hash[:12]}…).")

    def _verify_echo(self, role: str, version: int, hash_: str, proposal: ProposalRef) -> None:
        if version != proposal.version or hash_ != proposal.sha256:
            raise Escalation(
                SessionState.FAILED,
                f"{role} referenced proposal v{version} ({str(hash_)[:12]}…) but the "
                f"current proposal is v{proposal.version} ({proposal.sha256[:12]}…).",
            )

    def _consensus_result(self) -> ConsensusResult:
        proposal = self.record.latest_proposal
        return check_candidate_consensus(
            self.last_architect,
            self.last_reviewer,
            proposal,
            self._proposal_text() if proposal else "",
            self.registry,
            self.requirements,
            self.config.agreement,
        )

    def _validate_judge_approval(self, status: JudgeStatus, proposal: ProposalRef) -> None:
        problems = []
        consensus = self._consensus_result()
        if not consensus.ok:
            problems.append(f"candidate consensus is not valid ({'; '.join(consensus.reasons)})")
        statement = status.approval_statement or ""
        if str(proposal.version) not in statement or (
            proposal.sha256 not in statement and proposal.sha256[:12] not in statement
        ):
            problems.append(
                "approval_statement does not reference the exact proposal version and hash"
            )
        if self.registry.open_blocking():
            problems.append("blocking findings remain open")
        if self.requirements is not None:
            verdicts = {v.requirement_id: v.verdict for v in status.requirement_verdicts}
            for req in self.requirements.requirements:
                if req.priority == RequirementPriority.MUST and verdicts.get(req.id) != "ADDRESSED":
                    problems.append(
                        f"mandatory requirement {req.id} is not verified as ADDRESSED "
                        f"(verdict: {verdicts.get(req.id, 'missing')})"
                    )
        if problems:
            raise Escalation(
                SessionState.FAILED,
                "Judge returned APPROVED but the approval is invalid: "
                + "; ".join(problems),
            )

    def _check_common_escalations(
        self, role: str, decision: str, human_questions: list[str], summary: str
    ) -> None:
        if decision == "HUMAN_REQUIRED":
            questions = "; ".join(human_questions) or summary or "unspecified"
            raise Escalation(
                SessionState.AWAITING_HUMAN,
                f"{role} requires human input: {questions}",
            )
        if decision == "BLOCKED":
            raise Escalation(
                SessionState.BLOCKED,
                f"{role} reports the task is blocked: {summary or 'no detail provided'}",
            )

    def _apply_architect_finding_responses(self, status: ArchitectStatus) -> None:
        human_needed = []
        for resp in status.finding_responses:
            if not self.registry.has(resp.finding_id):
                continue
            finding = self.registry.get(resp.finding_id)
            finding.history.append(
                f"{utcnow_iso()} architect {resp.action}: {resp.response[:300]}"
            )
            if resp.action == "HUMAN_REQUIRED":
                self.registry.mark_human_required(resp.finding_id, resp.response)
                human_needed.append(resp.finding_id)
        self._save_registry()
        if human_needed:
            raise Escalation(
                SessionState.AWAITING_HUMAN,
                "Architect escalated findings to a human: " + ", ".join(human_needed),
            )

    def _safe_resolve(self, finding_ids: list[str], *, by_role: str) -> None:
        fixed_ids = {
            r.finding_id
            for r in (self.last_architect.finding_responses if self.last_architect else [])
            if r.action == "FIXED"
        }
        for fid in finding_ids:
            if not self.registry.has(fid):
                continue
            finding = self.registry.get(fid)
            try:
                # A judge finding may be closed by the reviewer only after the
                # architect actually addressed it (FIXED); a defense is not a
                # resolution — only the judge itself can accept a defense.
                if (
                    by_role == "reviewer"
                    and finding.source_role == "judge"
                    and fid not in fixed_ids
                ):
                    raise FindingLifecycleError(
                        f"judge finding {fid} was not fixed by the architect "
                        "(no FIXED response); the reviewer cannot resolve it"
                    )
                self.registry.resolve([fid], by_role=by_role)
            except FindingLifecycleError as exc:
                self.transcript.note(
                    self.record.id,
                    f"Rejected improper resolution of {fid} by {by_role}: {exc}",
                    kind="error", round_no=self.record.round,
                    judge_cycle=self.record.judge_cycle, role=by_role,
                )

    def _save_registry(self) -> None:
        atomic_write_json(self.store.findings_json, self.registry.dump())

    def _decision_note(self, text: str) -> None:
        path = self.store.decisions_md
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# Decisions Log — session {self.record.id}\n\n", encoding="utf-8")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"- {utcnow_iso()} — {text}\n")

    def _decisions_log_text(self) -> str:
        if self.store.decisions_md.is_file():
            return self.store.decisions_md.read_text(encoding="utf-8")
        return "_No decisions recorded._"

    def _write_raw_logs(self, invocation_id: str, stdout: str, stderr: str) -> None:
        if not self.config.session.saveRawLogs:
            return
        if self.config.security.redactEnvironmentVariables:
            stdout, stderr = redact(stdout), redact(stderr)
        for stream, content in (("stdout", stdout), ("stderr", stderr)):
            path = self.store.raw_log_path(invocation_id, stream)
            if not path.exists():
                write_immutable(path, content)

    def _requirements_markdown(self) -> str:
        if self.requirements is None:
            return "_Not yet extracted._"
        lines = ["### Requirements", ""]
        for r in self.requirements.requirements:
            lines.append(f"- **{r.id}** [{r.priority.value}] {r.text}")
        if self.requirements.acceptance_criteria:
            lines += ["", "### Acceptance Criteria", ""]
            for ac in self.requirements.acceptance_criteria:
                lines.append(f"- **{ac.id}** {ac.text}")
        return "\n".join(lines)

    def _open_findings_markdown(self) -> str:
        parts = [self.registry.to_markdown(only_open=True)]
        arbitration_note = getattr(self, "_arbitration_note", None)
        if arbitration_note:
            parts.append(f"\n**Judge arbitration ruling:** {arbitration_note}")
            self._arbitration_note = None
        reasons = getattr(self, "_consensus_failure_reasons", None)
        if reasons:
            parts.append(
                "\n**Additional consensus-check failures to address:**\n"
                + "\n".join(f"- {r}" for r in reasons)
            )
            self._consensus_failure_reasons = None
        return "\n".join(p for p in parts if p)

    def _architect_responses_markdown(self) -> str:
        if self.last_architect is None or not self.last_architect.finding_responses:
            return ""
        return "\n".join(
            f"- **{r.finding_id}** — {r.action}: {r.response}"
            for r in self.last_architect.finding_responses
        )

    def _latest_artifact_text(self, directory: Path) -> str:
        if not directory.is_dir():
            return ""
        files = sorted(p for p in directory.iterdir() if p.suffix == ".md")
        return files[-1].read_text(encoding="utf-8") if files else ""

    def _rebuild_statuses_from_checkpoints(self) -> None:
        for inv in self.record.invocations:
            try:
                if inv.role == "architect":
                    self.last_architect = ArchitectStatus.model_validate(inv.status_json)
                elif inv.role == "reviewer":
                    self.last_reviewer = ReviewerStatus.model_validate(inv.status_json)
                elif inv.role == "judge":
                    self.last_judge = JudgeStatus.model_validate(inv.status_json)
            except Exception:
                continue
