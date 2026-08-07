# TASK: <one-line name>

<!--
AI Council task template. Copy this file, delete the comments, and fill it
in. Every section below exists because leaving it out reliably costs debate
rounds: an ambiguity you don't resolve here becomes a reviewer finding the
architect has to litigate later. Sharp inputs are the single biggest lever
on session length. Sections marked (optional) can be deleted if truly
irrelevant.
-->

## Objective

<!-- 2-5 sentences: what exists when this is done, and why it's wanted.
     State the user-visible outcome, not the implementation. -->

## Context (optional)

<!-- What already exists that the council should build on rather than
     rebuild: relevant directories, prior art, known constraints of the
     surrounding system. Pointing at existing code prevents "rebuild it"
     proposals and "does not reuse X" findings. -->

## Requirements

<!-- Numbered, one obligation per line, MUST/SHOULD marked explicitly.
     These become REQ-001... and the Judge verifies every one, so write
     only what you actually require. -->

1. It MUST ...
2. It MUST ...
3. It SHOULD ...

## Acceptance criteria

<!-- Testable statements — each becomes AC-001... and needs a validation
     method. "Re-running the import produces no duplicates" is testable;
     "the code is clean" is not. -->

- ...

## Out of scope / non-goals

<!-- The highest-leverage section in this file. Strict reviewers will
     otherwise invent scope for you. Name the adjacent things you are
     deliberately NOT asking for, e.g.:
     - No support for <adjacent format/platform/use case>
     - No performance work beyond <bound>
     - No migration of <existing thing>
-->

- ...

## Risk tolerances & accepted trade-offs

<!-- Pre-answer the severity debates. State the risks you accept so a
     reviewer cannot rate them BLOCKING, e.g.:
     - A small check-then-act (TOCTOU) window on <file> is acceptable;
       formal atomicity guarantees are NOT required.
     - Concurrent invocations are out of scope; no locking is required.
     - Best-effort error messages are sufficient; no retry logic needed.
     Whatever you leave unstated here, the council must either escalate to
     you (AWAITING_HUMAN) or argue about (rounds). -->

- ...

## Constraints (optional)

<!-- Hard rules the solution must operate within:
     - Dependency policy: e.g. "new dependencies require approval" or
       "xgboost/lightgbm/torch are pre-approved" (pre-answering this
       avoids a HUMAN_REQUIRED escalation mid-session)
     - Language/framework/versions; compatibility requirements
     - Budget/timeline bounds, API cost limits
-->

- ...

## Definitions (optional)

<!-- Terms that could be read two ways, pinned to one meaning.
     ("Idempotent means: re-running with the same input file produces
     byte-identical database state.") -->

## Evidence expectations (optional)

<!-- What proof of completion you expect (tests, benchmarks, traceability),
     and for implement mode, the test command the orchestrator should run:
     configure `implementation.testCommand` in ai-council.yaml. -->
