# TASK: Build AI Council — Autonomous Claude Code, Codex, and Judge Collaboration Framework

## Objective

Design and implement a reusable local framework that allows Claude Code and ChatGPT Codex to collaborate autonomously on engineering problems without requiring a human to manually relay messages between them.

The framework will operate as an **AI Council** with three primary roles:

1. **Claude Code — Solution Architect**
2. **Codex — Critical Reviewer**
3. **Judge — Independent Evaluator**

Claude and Codex must exchange proposals, reviews, revisions, disagreements, and status updates until they believe they have reached agreement.

The Judge must then independently determine whether the proposed solution actually satisfies the original task and is ready to be accepted.

The desired command-line experience is:

```bash
ai-council discuss TASK.md
```

The command should produce one of the following outcomes:

- an approved final plan
- an approved implementation
- a request for additional revisions
- a human-intervention report
- a failure report with recovery instructions

The human should not need to participate in each interaction.

---

# Core Principles

The framework must:

- minimize human involvement
- preserve a complete audit trail
- encourage constructive disagreement
- prevent superficial or premature agreement
- verify every original requirement
- detect unresolved contradictions
- prevent infinite loops
- support resuming interrupted sessions
- isolate agent responsibilities
- support additional agents in the future
- work safely inside arbitrary software repositories

The Judge must be independent from the Architect and Reviewer.

The Judge must not approve a proposal merely because Claude and Codex agree.

---

# High-Level Architecture

```text
                         User
                           │
                           ▼
                 AI Council Orchestrator
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
       Claude Code                  Codex
   Solution Architect          Critical Reviewer
              │                         │
              └────────────┬────────────┘
                           │
                  Candidate Consensus
                           │
                           ▼
                         Judge
                 Independent Evaluation
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          APPROVED       REVISE     HUMAN_REQUIRED
```

The agents must not communicate through uncontrolled free-form processes.

The orchestrator must:

- invoke each CLI
- construct prompts
- capture responses
- validate structured output
- maintain proposal versions
- maintain the transcript
- track requirement coverage
- route feedback between agents
- invoke the Judge
- apply termination rules
- produce the final report

---

# Collaboration Lifecycle

The default lifecycle is:

```text
1. Load original task
2. Extract requirements and acceptance criteria
3. Claude creates Proposal v1
4. Codex reviews Proposal v1
5. Claude revises or defends Proposal v1
6. Codex re-evaluates
7. Repeat until candidate consensus
8. Judge independently evaluates candidate
9. If rejected, route Judge findings back to Claude and Codex
10. Repeat until approved, blocked, or iteration limits are reached
```

Candidate consensus is not final approval.

Final approval requires the Judge.

---

# Agent Roles

## 1. Claude Code — Solution Architect

Claude Code is the primary solution architect and, when enabled by workflow configuration, the primary implementation agent.

### Responsibilities

Claude must:

- understand the original task
- identify explicit and implicit requirements
- identify assumptions
- create the proposed solution
- document architectural decisions
- address Codex review findings
- address Judge findings
- revise the proposal when necessary
- defend technically justified decisions
- identify unresolved human decisions
- produce an implementation-ready final plan
- increment proposal versions when material changes occur

Claude must not:

- agree merely to end the discussion
- ignore review findings without explanation
- silently remove requirements
- falsely claim tests or validations were performed
- increment the proposal version for formatting-only changes
- approve its own work as final

### Claude Decision Values

Claude may return:

- `PROPOSED`
- `REVISED`
- `AGREED`
- `DISAGREE`
- `HUMAN_REQUIRED`
- `BLOCKED`
- `ERROR`

---

## 2. Codex — Critical Reviewer

Codex is the senior technical reviewer.

Its purpose is to challenge the proposal and uncover weaknesses before the proposal reaches the Judge.

### Responsibilities

Codex must evaluate:

- correctness
- completeness
- architecture
- implementation feasibility
- failure modes
- security
- data integrity
- concurrency
- idempotency
- performance
- maintainability
- observability
- testing
- deployment
- rollback
- backward compatibility
- operational risk
- documentation
- requirement coverage

Codex must:

- cite specific proposal sections when raising issues
- distinguish blocking issues from recommendations
- explain why each blocking issue matters
- propose concrete acceptance conditions
- reconsider issues after Claude responds
- explicitly mark resolved findings
- identify new findings separately from existing findings

Codex must not:

- reject proposals based only on stylistic preferences
- repeatedly raise resolved issues without new evidence
- rewrite the entire proposal unless structurally necessary
- agree merely to allow the workflow to terminate
- approve a proposal containing unresolved blocking findings

### Codex Decision Values

Codex may return:

- `APPROVE_FOR_JUDGE`
- `REVISE`
- `DISAGREE`
- `HUMAN_REQUIRED`
- `BLOCKED`
- `ERROR`

---

## 3. Judge — Independent Evaluator

The Judge is the final independent quality gate.

The Judge must evaluate the candidate solution against the original task, not merely against the opinions of Claude and Codex.

The Judge may be powered by:

- a separate configured model
- Claude with a fully isolated Judge prompt
- Codex with a fully isolated Judge prompt
- another supported CLI agent
- multiple Judges under a future quorum configuration

The Judge must receive sufficient context to evaluate the solution, but it should not be biased by unnecessary persuasive discussion.

### Recommended Judge Inputs

The Judge should receive:

- the original task
- extracted requirements
- acceptance criteria
- current proposal
- latest Codex review
- unresolved issue list
- decisions log
- test or validation evidence
- concise consensus summary

The full transcript may be made available as an optional reference, but the Judge should first evaluate the candidate using the authoritative artifacts.

### Judge Responsibilities

The Judge must independently verify:

1. Every original requirement is addressed.
2. Every acceptance criterion is testable.
3. No blocking issue remains unresolved.
4. Assumptions are clearly documented.
5. Important risks have mitigations.
6. The solution is internally consistent.
7. The implementation is feasible.
8. The test plan validates the important behavior.
9. Operational and failure scenarios are covered.
10. Claims of completion are supported by evidence.
11. Claude and Codex agreed on the same proposal version.
12. No material changes occurred after the last review.
13. Human input is not being avoided by inventing assumptions.
14. The proposed solution does not exceed the authorized scope.

### Judge Authority

The Judge may:

- approve the candidate
- reject the candidate
- request targeted revisions
- reopen previously resolved issues
- identify new blocking findings
- require evidence
- request human intervention
- mark the session blocked

The Judge must not:

- directly modify the proposal
- silently fix missing content
- approve based solely on model confidence
- approve merely because both agents agree
- introduce unrelated scope
- replace human decisions when requirements are genuinely ambiguous

### Judge Decision Values

The Judge may return:

- `APPROVED`
- `REVISE`
- `EVIDENCE_REQUIRED`
- `HUMAN_REQUIRED`
- `BLOCKED`
- `ERROR`

Only `APPROVED` constitutes final council approval.

---

# Optional Multiple-Judge Support

Design the framework so multiple Judges can be added later.

Example:

```yaml
judges:
  mode: quorum
  requiredApprovals: 2

  agents:
    - name: architecture-judge
      adapter: codex

    - name: security-judge
      adapter: claude

    - name: test-judge
      adapter: codex
```

Potential approval modes:

- `single`
- `unanimous`
- `majority`
- `quorum`

The initial implementation only needs to support one Judge, but the abstractions must not prevent multi-Judge support.

---

# Repository and Working Directory

Use a repository-local working directory:

```text
.ai-council/
├── config.yaml
├── problem.md
├── requirements.json
├── proposal.md
├── review.md
├── judge-report.md
├── decisions.md
├── transcript.md
├── status.json
├── final-plan.md
├── unresolved.md
├── evidence/
├── prompts/
│   ├── architect.md
│   ├── reviewer.md
│   └── judge.md
├── sessions/
│   └── <session-id>/
│       ├── session.json
│       ├── problem.md
│       ├── requirements.json
│       ├── transcript.jsonl
│       ├── final-report.md
│       ├── proposals/
│       │   ├── proposal-v001.md
│       │   └── proposal-v002.md
│       ├── reviews/
│       │   ├── review-v001-r001.md
│       │   └── review-v002-r001.md
│       ├── judgments/
│       │   ├── judgment-v002-j001.md
│       │   └── judgment-v003-j002.md
│       ├── evidence/
│       └── logs/
└── README.md
```

Each session must have a unique ID.

Example:

```text
20260801-192900-a4f82c
```

Artifacts from previous rounds must never be overwritten.

Convenience files at the `.ai-council/` root may point to or copy the latest session artifacts.

---

# Requirement Extraction

Before the first proposal, the orchestrator must create a normalized list of requirements from the original task.

Store it in:

```text
requirements.json
```

Example:

```json
{
  "task_hash": "sha256-value",
  "requirements": [
    {
      "id": "REQ-001",
      "text": "Claude and Codex must exchange structured status updates.",
      "source": {
        "file": "TASK.md",
        "section": "Objective"
      },
      "priority": "MUST",
      "status": "OPEN",
      "covered_by": [],
      "validation": []
    }
  ],
  "acceptance_criteria": [
    {
      "id": "AC-001",
      "text": "Both agents must approve the same proposal version before Judge evaluation.",
      "status": "OPEN",
      "evidence": []
    }
  ]
}
```

Each proposal must include a requirement-coverage matrix.

The Judge must evaluate this matrix against the original task rather than trusting it automatically.

---

# Proposal Versioning

Every materially different proposal must have an immutable version.

Example:

```text
proposal-v001.md
proposal-v002.md
proposal-v003.md
```

Only the Solution Architect may create a new proposal version.

A new version is required when changes affect:

- architecture
- behavior
- scope
- interfaces
- dependencies
- data structures
- security
- tests
- deployment
- acceptance criteria
- implementation sequence

A new version is not required for:

- spelling corrections
- formatting
- non-material wording changes

Each proposal version must have a SHA-256 hash.

Codex and the Judge must reference both the proposal version and hash.

---

# Consensus Rules

Claude and Codex reach candidate consensus only when all of the following are true:

1. Claude returns `AGREED`.
2. Codex returns `APPROVE_FOR_JUDGE`.
3. Both reference the same proposal version.
4. Both reference the same proposal hash.
5. Codex has no unresolved blocking findings.
6. Claude has no unresolved objections.
7. The requirement matrix contains no unexplained missing requirements.
8. No material proposal change occurred after Codex's approval.

Candidate consensus then triggers Judge evaluation.

Candidate consensus must never be represented as final approval.

---

# Judge Approval Rules

The Judge may return `APPROVED` only when:

1. Candidate consensus is valid.
2. The proposal hash matches the reviewed hash.
3. Every mandatory requirement is addressed.
4. Every acceptance criterion has a validation method.
5. No blocking issue remains unresolved.
6. No required evidence is missing.
7. The proposal is internally consistent.
8. The proposed implementation is feasible.
9. Risks and failure modes are adequately addressed.
10. Human input is not required.

The Judge response must include an explicit approval statement tied to the exact proposal version and hash.

---

# Judge Rejection and Revision Flow

When the Judge returns `REVISE`:

1. Save the Judge report immutably.
2. Add each Judge finding to the issue registry.
3. Route the findings to Claude.
4. Claude must respond to every finding.
5. Claude creates a new proposal version if material changes are made.
6. Codex reviews the new proposal.
7. Claude and Codex must reach candidate consensus again.
8. Invoke the Judge on the new candidate.

Codex's prior approval must not carry over to a new proposal version.

The Judge's prior rejection must remain part of the audit trail.

---

# Findings Registry

Maintain a structured registry of all findings.

Finding severity values:

- `BLOCKING`
- `MAJOR`
- `MINOR`
- `ADVISORY`

Finding status values:

- `OPEN`
- `ACCEPTED`
- `RESOLVED`
- `WONT_FIX`
- `HUMAN_REQUIRED`
- `SUPERSEDED`

A blocking finding cannot be marked `WONT_FIX` without human authorization.

---

# Structured Agent Responses

Every agent response must contain:

1. A human-readable Markdown section.
2. Exactly one machine-readable JSON object in a clearly delimited block.

Recommended delimiter:

```text
<AI_COUNCIL_STATUS>
{
  ...
}
</AI_COUNCIL_STATUS>
```

Do not rely on finding the last arbitrary JSON object in the response.

Use formal JSON Schema validation for architect, reviewer, Judge, session, requirement, and finding records.

Invalid structured output must not advance the workflow.

On validation failure:

1. Retry the same agent with a correction prompt.
2. Include the validation error.
3. Do not count the correction retry as a substantive debate round.
4. Stop after the configured retry limit.
5. Preserve invalid responses in logs.

---

# Prompt Templates

Store prompts as version-controlled templates:

```text
prompts/
├── requirement-extractor.md
├── architect-initial.md
├── architect-revision.md
├── reviewer.md
├── judge.md
└── format-repair.md
```

Templates should provide:

- original task
- normalized requirements
- current proposal
- exact proposal version and hash
- latest review
- latest judgment
- open findings
- decision log
- evidence references

The Judge prompt must explicitly state:

- The Judge is not part of the Claude–Codex negotiation.
- Agreement between agents is evidence, not proof.
- The proposal must be evaluated against the original task.
- The Judge must not repair missing content itself.
- Missing requirements must not be inferred as complete.
- Unsupported claims must not be approved.
- Final approval must reference the exact proposal version and hash.

---

# CLI Commands

Implement a CLI named:

```bash
ai-council
```

Required commands:

```bash
ai-council discuss TASK.md
ai-council discuss TASK.md --config ai-council.yaml
ai-council resume <session-id>
ai-council status <session-id>
ai-council transcript <session-id>
ai-council proposal <session-id>
ai-council judgment <session-id>
ai-council export <session-id> --format markdown
```

Nice-to-have commands:

```bash
ai-council list
ai-council inspect
ai-council validate-config
ai-council doctor
ai-council cancel
```

Support quiet and verbose modes.

---

# Agent Adapter Architecture

Do not hardcode orchestration logic directly to Claude or Codex command syntax.

Create a generic adapter interface.

Initial adapters:

- `ClaudeCodeAdapter`
- `CodexAdapter`
- `MockAgentAdapter`

The Judge must use the same adapter abstraction.

It must be possible to assign Claude or Codex to any role through configuration.

---

# Process Execution Requirements

Agent CLI processes must be invoked safely.

Implement:

- argument arrays rather than shell-concatenated commands
- configurable working directory
- environment-variable allowlists
- process timeout
- stdout capture
- stderr capture
- exit-code capture
- cancellation handling
- retry behavior
- maximum output size
- secret redaction
- immutable raw logs

Do not use `shell=True` unless absolutely required and documented.

---

# Repository Safety

Discussion mode should be read-only by default.

Default:

```yaml
workspace:
  mode: read-only
```

Future modes:

- `read-only`
- `worktree`
- `direct-write`

For implementation workflows, prefer an isolated Git worktree.

Never permit destructive Git commands by default.

---

# Configuration

Support YAML configuration.

Example:

```yaml
version: 1

session:
  maxDebateRounds: 8
  maxJudgeCycles: 3
  maxFormatRetries: 2
  maxAgentFailures: 2
  repeatedDisagreementLimit: 2
  saveRawLogs: true
  archiveEveryRound: true
  resumable: true

agreement:
  minimumConfidence: 0.85
  requireMatchingProposalHash: true
  requireNoBlockingFindings: true

agents:
  architect:
    adapter: claude-code
    model: default
    timeoutSeconds: 900

  reviewer:
    adapter: codex
    model: default
    timeoutSeconds: 900

  judge:
    adapter: codex
    model: default
    timeoutSeconds: 900
    isolatedContext: true

workspace:
  mode: read-only
  root: .
  allowCommands: false

output:
  console: true
  markdownReport: true
  jsonReport: true
  htmlTranscript: false

security:
  redactEnvironmentVariables: true
  allowedEnvironmentVariables:
    - PATH
    - HOME
  maximumCapturedOutputBytes: 2000000
```

Configuration priority:

1. command-line options
2. repository config
3. user config
4. built-in defaults

---

# State Machine

Implement the workflow as an explicit state machine.

Suggested states:

```text
INITIALIZING
EXTRACTING_REQUIREMENTS
ARCHITECT_PROPOSING
REVIEWER_REVIEWING
ARCHITECT_REVISING
CANDIDATE_CONSENSUS
JUDGE_EVALUATING
JUDGE_REJECTED
AWAITING_HUMAN
APPROVED
BLOCKED
FAILED
CANCELLED
```

Persist state after every transition.

The orchestrator must be able to recover after interruption without repeating completed agent calls unnecessarily.

---

# Reliability Requirements

Implement:

- atomic file writes
- resumable sessions
- invocation IDs
- response parsing checkpoints
- retry limits
- loop detection
- repeated-disagreement detection
- proposal-hash cycle detection
- timeout handling
- failure escalation
- focused human-intervention reports

Stop or escalate when:

- maximum debate rounds are reached
- maximum Judge cycles are reached
- the same blocking disagreement repeats
- proposals alternate between prior hashes
- no material proposal change follows a revision request
- structured output repeatedly fails validation
- an agent repeatedly fails
- human clarification is genuinely required
- the task is impossible under current permissions

---

# Evidence System

The Judge must be able to require evidence.

Evidence may include:

- test results
- lint output
- type-check output
- benchmark output
- Git diff
- static-analysis output
- requirement traceability
- command logs
- validation reports

Every evidence item must include metadata such as:

- evidence ID
- type
- creation time
- command
- exit code
- artifact path
- SHA-256 hash

The system must never represent an unexecuted test as passed evidence.

---

# Transcript and Reporting

Maintain both:

```text
transcript.jsonl
transcript.md
```

Each event should include:

- event ID
- timestamp
- session ID
- round
- Judge cycle
- agent and role
- invocation ID
- prompt version and hash
- proposal version and hash
- response
- parsed status
- duration
- exit code
- retry count
- usage estimate when available

On Judge approval, create:

```text
final-plan.md
final-report.md
final-report.json
```

The final report must clearly state `Approved by Judge` only after a valid Judge `APPROVED` response.

---

# Planning and Future Implementation Modes

The first required release should implement:

```bash
ai-council discuss TASK.md
```

Design for a future workflow:

```bash
ai-council implement TASK.md
```

Potential implementation lifecycle:

```text
Claude implements
Codex reviews the diff
Claude fixes findings
Tests run
Codex approves the implementation
Judge evaluates requirements, diff, and evidence
Judge approves or rejects
```

Do not overbuild implementation mode before planning mode is stable, but keep the architecture extensible.

---

# Recommended Technology

Python is preferred unless the repository strongly indicates another choice.

Suggested stack:

- Python 3.11+
- `typer`
- `pydantic`
- `PyYAML`
- `rich`
- `jinja2`
- `pytest`

Use standard-library functionality where practical.

---

# Testing Requirements

Implement comprehensive automated tests.

## Unit Tests

Test:

- configuration merging
- proposal versioning
- hash generation
- response extraction
- JSON Schema validation
- state transitions
- agreement detection
- Judge approval detection
- finding lifecycle
- repeated disagreement detection
- redaction
- atomic persistence
- timeouts
- retries

## Integration Tests

Use fake adapters to test:

1. Claude and Codex agree; Judge approves.
2. Codex requests revision; Claude fixes it; Judge approves.
3. Agents agree; Judge rejects; agents revise; Judge approves.
4. Judge rejects repeatedly; maximum Judge cycles are reached.
5. An agent references an outdated proposal version.
6. Proposal version matches but hash does not.
7. Malformed JSON is repaired.
8. Malformed JSON repeatedly fails.
9. An agent times out.
10. A session is interrupted and resumed.
11. Human input is required.
12. A blocking finding is improperly marked resolved.
13. Proposal changes after reviewer approval.
14. Judge requests evidence.
15. Agents reach superficial consensus with an unmet requirement.
16. Repeated disagreement is detected.
17. Secrets are redacted.
18. Read-only mode prevents repository modification.

Provide an opt-in live end-to-end test for installed Claude Code and Codex CLIs.

The standard test suite must not require live model access.

---

# Mock Agent Support

Provide deterministic mock adapters and fixtures so all orchestration behavior can be tested without API costs or installed CLIs.

---

# Required Deliverables

The implementation must include:

1. Working `ai-council` CLI.
2. Claude Code adapter.
3. Codex adapter.
4. Generic Judge support.
5. Mock agent adapter.
6. Explicit workflow state machine.
7. Structured response validation.
8. Requirement extraction and tracking.
9. Proposal versioning and hashing.
10. Findings registry.
11. Candidate consensus detection.
12. Independent Judge evaluation.
13. Judge rejection and revision flow.
14. Configurable iteration limits.
15. Session persistence.
16. Resume functionality.
17. Complete transcript preservation.
18. Markdown and JSON final reports.
19. Unit and integration tests.
20. Example configuration.
21. Example prompts.
22. Sample approved session.
23. Sample Judge-rejected session.
24. Complete documentation.

---

# Success Criteria

The task is complete when:

- Claude and Codex exchange autonomous status updates.
- The user does not manually relay responses.
- Claude produces versioned proposals.
- Codex produces structured findings.
- Both agree on the exact same proposal version and hash.
- Their agreement triggers Judge evaluation.
- The Judge evaluates the original requirements independently.
- The Judge can reject a candidate accepted by both agents.
- Judge findings route back into the debate.
- Revised proposals require new reviewer approval.
- Only a valid Judge `APPROVED` decision completes the workflow.
- Infinite loops and repeated disagreements are bounded.
- Interrupted sessions can be resumed.
- Full transcripts and immutable artifacts are retained.
- Invalid structured responses are repaired or safely rejected.
- The normal test suite runs without live Claude or Codex access.
- Repository modifications are disabled by default in discussion mode.
- The architecture supports adding more agents and Judges later.

---

# Implementation Process

Before writing substantial code:

1. Inspect the current repository.
2. Identify its language, package structure, test framework, and conventions.
3. Document the proposed architecture.
4. Create a concise implementation plan.
5. Identify assumptions.
6. Identify dependencies.
7. Implement the smallest complete vertical slice first.
8. Add tests throughout implementation.
9. Run the complete test suite.
10. Document commands and results.

Do not replace working repository conventions unnecessarily.

Do not claim completion unless the acceptance criteria have been validated.

---

# Suggested Delivery Phases

## Phase 1 — Core Domain

Implement models, configuration, sessions, proposal versions, findings, response schemas, and state machine.

## Phase 2 — Agent Execution

Implement the generic adapter, Claude Code adapter, Codex adapter, mock adapter, and safe subprocess execution.

## Phase 3 — Debate Workflow

Implement the architect proposal, reviewer critique, revision loop, candidate consensus, and transcript persistence.

## Phase 4 — Judge Workflow

Implement the Judge prompt, Judge response schema, independent evaluation, rejection routing, approval enforcement, and Judge-cycle limits.

## Phase 5 — Reliability

Implement atomic persistence, resume, retries, validation repair, cancellation, loop detection, and secret redaction.

## Phase 6 — Reporting and Documentation

Implement final outputs, status views, transcript export, examples, and documentation.

---

# Final Instruction to Claude Code

Implement this as a production-quality, reusable local tool.

Favor explicit state, immutable artifacts, deterministic tests, strict validation, and clear failure behavior.

Do not treat agreement between Claude and Codex as final approval.

The Judge is the final independent authority, and approval must always be tied to the exact reviewed proposal version and SHA-256 hash.
