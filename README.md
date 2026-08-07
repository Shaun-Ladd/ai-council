# AI Council

Autonomous collaboration framework for **Claude Code**, **Codex**, and an
independent **Judge**. Point it at a task file and the agents debate, revise,
and converge on an implementation-ready plan — without a human relaying
messages — while an independent Judge decides whether the result actually
satisfies the original task.

```bash
ai-council discuss TASK.md
```

Outcomes: an approved final plan, a revision request, a human-intervention
report, or a failure report with recovery instructions.

## How it works

```text
                         User
                           │
                           ▼
                 AI Council Orchestrator
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
       Claude Code                  Codex
   Solution Architect          Critical Reviewer
              │                         │
              └────────────┬────────────┘
                           │
                  Candidate Consensus
                           ▼
                         Judge
                 Independent Evaluation
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          APPROVED       REVISE     HUMAN_REQUIRED
```

1. Requirements and acceptance criteria are extracted from the task into
   `requirements.json`.
2. The **Architect** (Claude Code by default) produces an immutable,
   SHA-256-hashed **proposal version** with a requirement-coverage matrix.
3. The **Reviewer** (Codex by default) challenges it: structured findings with
   severity (`BLOCKING`/`MAJOR`/`MINOR`/`ADVISORY`), cited sections, and
   acceptance conditions. The architect fixes or defends; every material
   change creates a new immutable proposal version.
4. **Candidate consensus** requires: architect `AGREED` + reviewer
   `APPROVE_FOR_JUDGE`, both citing the *same version and hash*, no open
   blocking findings, no unresolved objections, no uncovered requirements, and
   confidence above the configured threshold. Consensus is *not* approval.
5. The **Judge** — an isolated invocation, independent of the debate —
   evaluates the candidate against the *original task*, requirement by
   requirement. It can reject a candidate both agents accepted, demand
   evidence, reopen findings, or escalate to a human. Only a valid Judge
   `APPROVED`, tied to the exact proposal version and hash, completes the
   workflow.
6. Everything is persisted: append-only transcripts (`.jsonl` + `.md`),
   immutable proposals/reviews/judgments, a findings registry, decisions log,
   and final reports. Interrupted sessions resume without repeating completed
   agent calls.

Every agent reply must end with exactly one machine-readable block:

```text
<AI_COUNCIL_STATUS>
{ "role": "reviewer", "decision": "APPROVE_FOR_JUDGE", ... }
</AI_COUNCIL_STATUS>
```

Replies are schema-validated (pydantic); invalid output triggers a bounded
format-repair retry that does not consume a debate round.

## Install

Requires Python 3.11+.

**Global install (recommended)** — puts `ai-council` on your PATH so it can
be run from any repository:

```bash
pipx install git+https://github.com/Shaun-Ladd/ai-council.git
source ~/.zshrc   # reload your shell so PATH picks up the new command
ai-council --help
```

(No pipx? `brew install pipx && pipx ensurepath` first. `uv tool install`
works too. While this repository is private, installers must have GitHub
access to it.)

**Development install:**

```bash
git clone https://github.com/Shaun-Ladd/ai-council.git && cd ai-council
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/ai-council --help
```

For live sessions you also need the agent CLIs on your PATH (`claude`,
`codex`). Check with:

```bash
ai-council doctor
```

## Quickstart (no API access needed)

The committed sample sessions run on deterministic mock agents:

```bash
cd examples/sample-approved
ai-council list
ai-council transcript <session-id>
ai-council judgment <session-id>
```

Or regenerate them: `.venv/bin/python examples/generate_samples.py`.

For a real session, copy `examples/ai-council.yaml` into your repository,
adjust the adapters, and run `ai-council discuss TASK.md`.

## Expected flow

A successful `ai-council discuss` run looks like this in the terminal (each
agent's decision is followed by its own summary; `-v` streams full
responses):

```text
AI Council session 20260803-015921-031362 started.
 INITIALIZING -> EXTRACTING_REQUIREMENTS
 extract -> ok
 EXTRACTING_REQUIREMENTS -> ARCHITECT_PROPOSING
 propose -> PROPOSED            # architect: proposal v001 + coverage matrix
 ARCHITECT_PROPOSING -> REVIEWER_REVIEWING
 review -> REVISE               # reviewer: findings (e.g. missing deploy path)
 REVIEWER_REVIEWING -> ARCHITECT_REVISING
 revise -> REVISED              # architect: proposal v002 answering each finding
 ARCHITECT_REVISING -> REVIEWER_REVIEWING
 review -> APPROVE_FOR_JUDGE    # reviewer: no blocking findings remain
 REVIEWER_REVIEWING -> CANDIDATE_CONSENSUS
 confirm -> AGREED              # architect: agrees to the exact version + hash
 CANDIDATE_CONSENSUS -> JUDGE_EVALUATING
 judge -> APPROVED              # judge: independent check against the task
 JUDGE_EVALUATING -> APPROVED

APPROVED — Approved by Judge: proposal v002 (sha256 444ae2a2ac1f8c…).
Report:  .ai-council/sessions/20260803-015921-031362/final-report.md
```

The revise/review loop may repeat several times, and the run can instead end
`AWAITING_HUMAN` (answer with `ai-council human`, then `resume`), `BLOCKED`,
or `FAILED` — the report always says why and what to do next.

### What you get (and what it does NOT do)

Discussion mode **never touches your code**: it opens no PRs, merges
nothing, and makes no commits — agents run with write access disabled and
the tool writes only inside `.ai-council/`. The deliverable is the
Judge-approved plan:

```text
.ai-council/final-plan.md      # the approved, implementation-ready plan
.ai-council/final-report.md    # verdict, requirement coverage, findings
```

Want the council to write the code too? Use implement mode.

### Implement mode

```bash
ai-council implement TASK.md
```

Runs the full pipeline: the normal debate to a Judge-approved plan, then —
in an **isolated git worktree** on branch `ai-council/<session-id>` — the
architect implements the plan, the orchestrator captures every iteration as
a hashed, versioned diff and **runs your test command itself** (recording
real exit codes as evidence — agent claims are never trusted), the reviewer
critiques the diff with findings, the architect fixes, and once both agree
on the exact diff hash the Judge independently evaluates task + diff +
evidence. Approval requires green tests.

```yaml
implementation:
  testCommand: "pytest -q"     # run by the orchestrator in the worktree
  maxImplRounds: 8
  maxImplJudgeCycles: 3
```

Your checkout is never touched and nothing is merged or pushed for you — on
success the report gives you the branch and the exact commands:

```bash
git merge ai-council/<session-id>           # adopt locally, or
git push -u origin ai-council/<session-id>  # push and open a PR
```

Write access: the architect runs with permissions enabled *inside the
worktree only* (`claude --dangerously-skip-permissions`, codex
`--sandbox workspace-write`); reviewer and judge remain read-only.

### Choosing a workflow: one shot vs plan checkpoint

Two ways to get to implemented code:

1. **One shot** — `ai-council implement TASK.md` runs plan debate and
   implementation in a single session. Use when you're happy to review the
   result at merge time (the branch is your checkpoint).
2. **Plan checkpoint** — debate first, read the plan yourself, then
   greenlight the build without re-debating:

   ```bash
   ai-council discuss TASK.md            # ends APPROVED, session <id>
   cat .ai-council/final-plan.md         # you review the plan
   ai-council implement --from-session <id>
   ```

`--from-session` seeds a new implement session from any Judge-**APPROVED**
discuss session: the approved plan is carried over with its **exact version
and SHA-256 hash** (verified against the artifact — a tampered plan file is
refused), requirements come along, provenance is recorded in the decisions
log, and the plan debate is skipped entirely. The task argument is optional
(the session's own task is used); if you do pass one, its hash must match
the task the plan was approved for — a changed task means the plan no longer
corresponds and must be re-debated. Sessions that ended any other way
(`AWAITING_HUMAN`, `BLOCKED`, …) cannot seed an implementation: resume them
to plan approval first.

## Commands

```bash
ai-council discuss TASK.md [--config ai-council.yaml] [--repo DIR] [-q|-v]
ai-council implement TASK.md         # plan debate + coded implementation
ai-council implement --from-session <id>   # implement an already-approved plan
ai-council resume <session-id>       # continue an interrupted session
ai-council human <session-id> ...    # record decisions on AWAITING_HUMAN sessions
ai-council status <session-id>
ai-council transcript <session-id> [--jsonl]
ai-council proposal <session-id> [--version N]
ai-council judgment <session-id>
ai-council export <session-id> --format markdown|json [-o FILE]
ai-council list
ai-council validate-config
ai-council doctor
```

Exit codes: `0` approved · `2` human required · `3` blocked · `4` failed ·
`5` cancelled.

### When the council needs you (`AWAITING_HUMAN`)

Sessions escalate when the agents hit a decision only a human can make
(accept a risk, settle a scope dispute). The final report lists the findings
awaiting you; record your decisions and resume — they are injected into the
agents' prompts as authoritative and cannot be re-litigated:

```bash
ai-council human <id> --wont-fix RVW-003 --note "risk accepted"   # accept a risk
ai-council human <id> --resolve  RVW-008 --note "decided: ..."    # decision made
ai-council human <id> --reopen   RVW-010 --note "must be fixed"   # require a fix
ai-council human <id> --answer   "free-text guidance for the agents"
ai-council resume <id>
```

## Configuration

Layered, highest wins: CLI options → repo config (`.ai-council/config.yaml`
or `ai-council.yaml`) → user config (`~/.config/ai-council/config.yaml`) →
defaults. See `examples/ai-council.yaml` for every option.

Any adapter can fill any role — architect, reviewer, and judge are pure
configuration:

```yaml
agents:
  architect: {adapter: claude-code, timeoutSeconds: 900}
  reviewer:  {adapter: codex, timeoutSeconds: 900}
  judge:     {adapter: codex, isolatedContext: true}
```

Adapters: `claude-code`, `codex`, and `mock` (deterministic scripted
responses for tests and demos). CLI flags per adapter can be adjusted with
`command:` and `extraArgs:` without code changes.

### Severity discipline

Live sessions showed strict reviewer models rating out-of-scope hardening
ideas as `BLOCKING`, holding consensus hostage for dozens of rounds. The
reviewer prompt now defines what BLOCKING *means*, and the orchestrator
enforces it mechanically:

- A reviewer `BLOCKING` finding must name what it violates in its
  `violates` field — a requirement/criterion ID (`REQ-003`, `AC-001`),
  `internal-consistency`, or `task-objective`.
- A BLOCKING finding that cites no violation is **automatically downgraded
  to MAJOR**: still visible to the architect and the Judge, but unable to
  block consensus. The downgrade is recorded in the finding's history and
  the transcript.
- Hardening beyond the task's stated scope is ADVISORY by instruction — the
  task defines the bar, and the reviewer may not raise it.
- Judge findings are exempt: the Judge is the final authority on severity.

### Delta revisions

By default the architect revises proposals with targeted **SEARCH/REPLACE
edit blocks** instead of regenerating the whole document each round:

```text
<<<<<<< SEARCH
exact text copied from the current proposal
=======
replacement text
>>>>>>> REPLACE
```

The **orchestrator** applies the edits deterministically, assembles the
complete new document itself, and hashes/stores it immutably — so the
version/hash/consensus contract is completely unchanged; only the expensive
regeneration is eliminated. This cuts late-round cost and generation time
from "entire proposal" to "the sections under dispute", which also shrinks
exposure to mid-stream connection drops and response truncation on long
documents.

Application is strict (every SEARCH must match exactly once). Failed edits
get a bounded correction retry with the precise error, and a full document
is always accepted as fallback — reliability never regresses below full
regeneration. Disable with `session.deltaRevisions: false`.

### Failure classification

Agent-invocation failures are classified and handled per kind rather than
uniformly burning the retry budget:

| Kind | Examples | Policy |
|---|---|---|
| `TRANSIENT` | connection closed mid-response, `ECONNRESET`, overloaded/5xx | Retried with exponential backoff on a dedicated budget (`maxTransientRetries: 5`, `transientBackoffSeconds: 15`); never counts against `maxAgentFailures` |
| `USAGE_LIMIT` | "hit your session limit · resets 3:10pm", 429/quota | **Fails fast** with the reset time in the report — retrying a wall only time removes wastes budget |
| `AUTH` | OAuth expired, not logged in, invalid key | **Fails fast** with a re-authenticate instruction |
| `TIMEOUT` / `AGENT` | wall-clock timeout, unknown nonzero exit | Classic `maxAgentFailures` budget |

Every failure is logged to the transcript with its kind
(`[TRANSIENT] transient API/network failure: 'Connection closed…'`), and
fail-fast reports include the exact recovery command
(`ai-council resume <id>`). Raw output of every attempt — including re-runs
after resume — is preserved immutably in the session's `logs/`.

### Adaptive model escalation

Use a cheap architect by default and pay for a stronger model only where the
debate shows it's needed:

```yaml
agents:
  architect:
    adapter: claude-code
    model: sonnet
    escalationModel: opus   # used only while contested findings are open
```

A finding becomes **contested** when the reviewer (or Judge) *reopens* it,
or re-raises its lineage under a new ID — the signal that the cheaper
model's fix didn't convince. While any contested finding is open, architect
revision rounds run on `escalationModel`; the moment they're all cleared,
revisions drop back to the base model automatically. Every switch is
recorded in the decisions log and transcript.

This stacks with the other guards: escalation is the first response to a
sticky finding; if even the escalated model can't satisfy the reviewer, the
churn guard hands the dispute to Judge arbitration, and unresolvable
demands still escalate to you. Escalation is off unless `escalationModel`
is set.

### Round limits: why the default is 15

`session.maxDebateRounds` defaults to **15**. This is a **ceiling, not a
target** — understanding that distinction is the key to choosing your own
value.

**Why a high ceiling costs nothing when things go well.** The moment the
reviewer approves and the architect confirms the same proposal hash, the
session goes to the Judge — whether that happens in round 2 or round 12.
Unused rounds are never consumed. In live testing, a well-matched debate
reached the Judge in 2–4 rounds regardless of the configured limit.

**Why the ceiling is rarely what saves you anyway.** Two guards intervene
long before round 15 in a pathological debate:

- The **reviewer-churn guard** trips after `reviewerChurnLimit` (default 3)
  wasted rounds — re-raised finding lineages, unauthorized reopens, or
  no-progress rounds — and hands the dispute to Judge **arbitration**, which
  overrules disproportionate findings with binding effect (and grants
  `arbitrationBonusRounds` extra headroom).
- Architect-side escalation: an architect that concludes a demand is
  impossible marks it `HUMAN_REQUIRED`, ending the session with a focused
  decision list for you rather than grinding onward.

So the round limit is a **backstop against slow, technically-progressing
debates that never quite converge** — the one failure mode the other guards
don't catch.

**Pros of 15 (vs a lower limit like 8):**

- Headroom for noisier model pairings. Weaker/cheaper architect models
  (e.g. Sonnet vs a frontier model) draw more findings per round and
  resolve fewer; in our live runs Sonnet was still making genuine progress
  at round 8 and would have converged given more budget.
- Fewer premature `BLOCKED` endings, which each require a human to inspect
  and `resume` with a raised limit — usually costlier than the extra rounds
  would have been.
- Convergent sessions are completely unaffected (see above).

**Cons of 15:**

- A debate that *is* slowly failing burns more wall-clock and tokens before
  you hear about it: each round is two full model calls (≈5–10 minutes and
  the associated API cost in live runs). Worst case is roughly double the
  time/cost of an 8-round ceiling before the `BLOCKED` report appears.
- Long sessions produce long transcripts and large findings registries,
  which grow the context each subsequent agent call must process.
- If you use the council interactively and prefer *fast failure* so you can
  refine the task and retry, a lower ceiling surfaces problems sooner.

**Recommendations:** keep 15 for unattended/overnight runs and cheaper
models; drop to ~8 in a repo config if you babysit runs and want early
signal; tune `reviewerChurnLimit` rather than the round limit if your
problem is a nitpicking reviewer, since churn → arbitration resolves
disputes far more decisively than extra rounds do.

The implementation phase has its own independent budget
(`implementation.maxImplRounds`, default 8) — plan-phase rounds never eat
into it, and all counters reset at the phase boundary.

## Safety

- Discussion mode is **read-only by default**: Claude Code runs with
  `--permission-mode plan`, Codex with `--sandbox read-only`.
- Agent processes are spawned from argv arrays (never `shell=True`), with an
  environment-variable allowlist, wall-clock timeouts, process-group kill,
  and output-size caps.
- Secrets (API-key patterns, tokens, private keys, sensitive env values) are
  redacted from every persisted artifact.
- Artifacts are immutable: nothing from a previous round is ever overwritten.

## Reliability

- Explicit state machine (`INITIALIZING → … → APPROVED/BLOCKED/FAILED/…`),
  state persisted atomically after every transition.
- Bounded loops: `maxDebateRounds`, `maxJudgeCycles`, `maxFormatRetries`,
  `maxAgentFailures`, repeated-disagreement detection, proposal-hash cycle
  detection, and no-material-change detection.
- Reviewer-churn guard: rounds where the reviewer re-raises an existing
  finding lineage under a new ID, or raises new findings while resolving
  nothing, accumulate churn points (`reviewerChurnLimit`).
- Judge arbitration at deadlock (`judgeArbitration`, on by default): when the
  churn limit or round limit is hit, the Judge rules `UPHELD`/`OVERRULED` on
  every open finding once per session. Overruled findings are closed and
  binding on the reviewer; the debate gains `arbitrationBonusRounds`. The
  Judge cannot approve during arbitration — approval still requires
  consensus plus a normal Judge evaluation. If arbitration is disabled,
  spent, or the Judge upholds the deadlock, the session escalates to a human
  instead of silently blocking.
- `ai-council resume <id>` continues after an interruption; completed agent
  invocations are checkpointed and never re-run.
- Stale references are rejected: a review or judgment that cites the wrong
  proposal version or hash is discarded and retried, never acted upon.

## Repository layout of a session

```text
.ai-council/
├── problem.md, requirements.json, proposal.md, review.md, judge-report.md,
│   decisions.md, transcript.md, final-plan.md, unresolved.md, status.json
│   (convenience copies of the latest session)
└── sessions/<yyyymmdd-hhmmss-xxxxxx>/
    ├── session.json            # state, checkpoints, counters
    ├── problem.md, requirements.json, findings.json, decisions.md
    ├── transcript.jsonl, transcript.md
    ├── proposals/proposal-v001.md, …      # immutable, SHA-256 hashed
    ├── reviews/review-v001-r001.md, …
    ├── judgments/judgment-v001-j01.md, …
    ├── evidence/               # content-addressed evidence items
    ├── logs/                   # immutable raw agent I/O (redacted)
    └── final-plan.md, final-report.md, final-report.json
```

## Testing

```bash
.venv/bin/pytest            # 94 tests, no network or agent CLIs required
```

Unit tests cover config merging, hashing, versioning, parsing, state
transitions, consensus rules, the findings lifecycle, loop guards, redaction,
atomic persistence, and the process runner. Integration tests drive the full
orchestrator with scripted mock agents through 18 scenarios, including: judge
rejection of an agreed candidate, stale version/hash references, malformed
JSON repair and exhaustion, timeouts, interrupt + resume, improper finding
resolution, evidence requests, superficial consensus, repeated disagreement,
secret redaction, and read-only enforcement.

Opt-in live end-to-end test (spends real tokens):

```bash
AI_COUNCIL_LIVE_E2E=1 .venv/bin/pytest tests/integration/test_live_e2e.py -s
```

## Design notes & extension points

- **Multi-judge**: the config schema already models a judge panel
  (`judges: {mode: quorum, requiredApprovals: N, agents: […]}`); the
  orchestrator invokes the judge through the same adapter abstraction, so a
  panel executor can be added without reshaping the workflow.
- **Implementation mode**: `ai-council implement TASK.md` (future) will reuse
  the same state machine with an implement→diff-review→test→judge lifecycle
  and `workspace.mode: worktree` isolation.
- **Prompt templates** live in `src/ai_council/prompts/` and can be
  overridden per-repository by placing same-named files in
  `.ai-council/prompts/`.
- See `docs/PLAN.md` for the architecture plan and `docs/TASK.md` for the
  original specification.

## Assumptions

- `claude -p` (print mode, prompt on stdin) and `codex exec -` are the
  non-interactive entry points; both are configurable via `command`/
  `extraArgs` if your installed versions differ.
- Requirement extraction is performed by the architect's adapter with a
  dedicated prompt and validated against a strict schema.
