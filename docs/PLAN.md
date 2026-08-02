# AI Council — Implementation Plan

Source specification: `docs/TASK.md` (copied from the original TASK.md).

## Goal

A production-quality local CLI, `ai-council`, that orchestrates an autonomous
three-role debate — Claude Code (Solution Architect), Codex (Critical
Reviewer), and an independent Judge — over an engineering task, producing an
approved plan, a revision request, a human-intervention report, or a failure
report, with a complete immutable audit trail.

## Technology

- Python 3.11+ (developed on 3.12)
- `typer` (CLI), `pydantic` v2 (models + validation), `PyYAML` (config),
  `rich` (console output), `jinja2` (prompt templates), `pytest` (tests)
- `src/` layout, installable package with a `ai-council` console script

## Architecture

```
src/ai_council/
├── models.py        # Domain models: decisions, findings, requirements,
│                    # structured agent status payloads, session state
├── hashing.py       # SHA-256 helpers for proposals, prompts, evidence
├── config.py        # Layered YAML config (CLI > repo > user > defaults)
├── statemachine.py  # Explicit workflow state machine w/ allowed transitions
├── storage.py       # Atomic writes, immutable artifact store, session layout
├── parsing.py       # <AI_COUNCIL_STATUS> extraction + schema validation
├── redaction.py     # Secret redaction for logs/transcripts
├── prompts.py       # Jinja2 template rendering (templates in prompts/)
├── transcript.py    # transcript.jsonl + transcript.md event log
├── registry.py      # Findings registry lifecycle
├── consensus.py     # Candidate-consensus rules (pure functions)
├── loopguard.py     # Round limits, hash-cycle & repeated-disagreement detection
├── evidence.py      # Evidence items with metadata + hashes
├── reporting.py     # final-plan / final-report (md + json), exports
├── orchestrator.py  # The debate + judge workflow engine (resumable)
├── cli.py           # typer app: discuss/resume/status/... commands
└── adapters/
    ├── base.py      # AgentAdapter interface + AgentInvocation result
    ├── process.py   # Safe subprocess runner (argv arrays, env allowlist,
    │                # timeout, output caps, redaction, raw logs)
    ├── claude_code.py
    ├── codex.py
    └── mock.py      # Deterministic scripted adapter for tests/examples
```

### Key design decisions

1. **Structured responses.** Every agent reply must contain exactly one
   `<AI_COUNCIL_STATUS>{...}</AI_COUNCIL_STATUS>` block. Payloads are
   validated with role-specific pydantic models (JSON Schema is exported from
   these models). Invalid output triggers a format-repair retry (not counted
   as a debate round), bounded by `maxFormatRetries`.
2. **Immutability.** Proposals, reviews, judgments, raw logs, and transcripts
   are append-only files under `.ai-council/sessions/<session-id>/`. Writers
   refuse to overwrite existing artifact files. Root-level convenience files
   (`proposal.md`, `review.md`, …) are copies of the latest session artifacts.
3. **Versioning + hashing.** Only the architect creates proposal versions;
   each version body is SHA-256 hashed. Reviewer approval and Judge approval
   must cite the exact version *and* hash; any mismatch invalidates consensus.
4. **Consensus is a pure function** over the latest architect status, latest
   reviewer status, findings registry, and proposal store — easy to unit test
   and impossible to shortcut.
5. **The Judge is independent.** It is invoked through the same adapter
   abstraction with `isolatedContext: true`, receives authoritative artifacts
   (task, requirements, proposal, latest review, unresolved findings,
   decisions, evidence summaries) rather than the persuasive transcript, and
   its prompt explicitly forbids approving on agreement alone. Roles are bound
   to adapters purely via configuration, so any CLI can fill any role. A
   `judges` panel abstraction wraps the single judge so quorum modes can be
   added later without reshaping the orchestrator.
6. **Resumability.** `session.json` records state, counters, and a checkpoint
   log of completed invocations (invocation IDs + artifact pointers). Resume
   reloads the session and continues from the last persisted state without
   re-invoking completed agent calls.
7. **Safety.** Subprocesses use argv arrays (never `shell=True`), an
   environment allowlist, timeouts, output-size caps, cancellation handling,
   and secret redaction before anything is persisted to transcripts (raw logs
   are kept separately, marked sensitive). Discussion mode defaults to
   `workspace.mode: read-only` and passes read-only sandbox flags to agent
   CLIs.

### State machine

```
INITIALIZING → EXTRACTING_REQUIREMENTS → ARCHITECT_PROPOSING
→ REVIEWER_REVIEWING ⇄ ARCHITECT_REVISING
→ CANDIDATE_CONSENSUS → JUDGE_EVALUATING
→ APPROVED | JUDGE_REJECTED (→ ARCHITECT_REVISING) | AWAITING_HUMAN | BLOCKED
Any state → FAILED | CANCELLED
```

State is persisted atomically after every transition.

### Termination / escalation rules

- `maxDebateRounds`, `maxJudgeCycles`, `maxFormatRetries`, `maxAgentFailures`
- Repeated-disagreement detection (same blocking disagreement signature
  `repeatedDisagreementLimit` times)
- Proposal-hash cycle detection (a "new" version reuses a prior hash)
- No-material-change detection after a revision request
- Escalation writes a focused human-intervention or failure report.

## Delivery phases

1. **Core domain** — models, config, hashing, state machine, storage,
   parsing, redaction (+ unit tests).
2. **Agent execution** — process runner, adapter interface, Claude/Codex/mock
   adapters (+ unit tests).
3. **Debate workflow** — requirement extraction, propose/review/revise loop,
   consensus detection, transcript persistence.
4. **Judge workflow** — judge prompt/schema, evaluation, rejection routing,
   approval enforcement, judge-cycle limits.
5. **Reliability** — resume, retries, format repair, loop detection,
   cancellation, evidence system.
6. **Reporting & docs** — final reports, status/transcript/export commands,
   example config and prompts, sample approved and judge-rejected sessions
   (generated with the mock adapter), README and docs.

## Assumptions

- `claude` CLI supports non-interactive invocation (`claude -p` with prompt on
  stdin); `codex` CLI supports `codex exec`. Exact flags are configurable per
  adapter (`extraArgs`) so users can adjust without code changes.
- Requirement extraction is performed by the architect adapter with a
  dedicated extractor prompt; a deterministic fallback extractor is not
  provided (mock adapters cover tests).
- The standard test suite uses only `MockAgentAdapter`; a live end-to-end
  test is opt-in via `AI_COUNCIL_LIVE_E2E=1`.

## Test strategy

- Unit tests for every pure component (config merge, hashing, versioning,
  parsing, state transitions, consensus, findings lifecycle, redaction,
  atomic writes, loop detection, timeouts/retries).
- Integration tests drive the full orchestrator with scripted mock adapters
  covering the 18 scenarios enumerated in the task (agreement, revision,
  judge rejection, limits, version/hash mismatches, malformed JSON repair and
  failure, timeout, interrupt+resume, human-required, improper finding
  resolution, post-approval proposal change, evidence requests, superficial
  consensus, repeated disagreement, secret redaction, read-only enforcement).
- Opt-in live E2E test exercising installed `claude` and `codex` CLIs.
