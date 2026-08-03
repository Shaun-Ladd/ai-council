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

## Commands

```bash
ai-council discuss TASK.md [--config ai-council.yaml] [--repo DIR] [-q|-v]
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
