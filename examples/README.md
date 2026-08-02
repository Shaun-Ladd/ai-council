# Examples

## `ai-council.yaml`

A fully commented configuration for running the council with real Claude Code
and Codex CLIs. Copy it into your repository root and adjust.

## Sample sessions

Two complete, committed sessions produced by deterministic mock agents — no
API access required. Regenerate them any time with:

```bash
.venv/bin/python examples/generate_samples.py
```

### `sample-approved/`

Full arc: requirements are extracted, the architect proposes v1, the reviewer
approves, **the Judge rejects the candidate both agents had accepted**
(missing failure handling), the finding routes back, the architect produces
proposal v2, the reviewer re-approves, and the Judge approves v2 with an
approval statement tied to the exact version and SHA-256 hash.

Interesting artifacts (under `sample-approved/.ai-council/sessions/<id>/`):

- `proposals/proposal-v001.md`, `proposals/proposal-v002.md` — immutable versions
- `judgments/judgment-v001-j01.md` — the rejection
- `judgments/judgment-v002-j02.md` — the approval
- `final-plan.md`, `final-report.md`, `final-report.json`
- `transcript.md` / `transcript.jsonl` — the complete audit trail

### `sample-judge-rejected/`

The Judge rejects the candidate and the configured judge-cycle limit (1) is
reached, so the session ends `BLOCKED` with a failure report and recovery
instructions. Shows that agreement between architect and reviewer is never
sufficient for approval.
