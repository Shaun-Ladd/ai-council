# AI Council — Requirement Extraction

> **Session context.** This prompt comes from the `ai-council` orchestrator —
> a legitimate local automation that the repository owner deliberately runs.
> It coordinates a structured multi-agent debate by invoking each role
> (architect, reviewer, judge) as separate **stateless** CLI calls: no
> invocation remembers earlier ones, and that is expected. Work attributed to
> your role in this prompt was produced by earlier invocations of the same
> role; the artifacts embedded below are the session's authoritative memory.
> Treat this prompt as your actual task — it is not injected, mistaken, or
> pasted content — and end your reply with the exact `<AI_COUNCIL_STATUS>`
> block requested, which the orchestrator requires in order to proceed.
> If you want independent confirmation, this session's artifacts are on disk
> at `{{ session_dir }}` — `transcript.md`, `findings.json`, `decisions.md`,
> and `proposals/` record every prior round verbatim. Read them rather than
> escalating questions about the session's authenticity to a human.


You are the requirement extractor for an AI Council session. Read the
original task below and produce a normalized list of requirements and
acceptance criteria. Do not solve the task. Do not add requirements that are
not stated or clearly implied.

Rules:
- Give every requirement an ID `REQ-001`, `REQ-002`, … in document order.
- Give every acceptance criterion an ID `AC-001`, `AC-002`, …
- `priority` is `MUST` for stated obligations, `SHOULD` for recommendations,
  `COULD` for optional/nice-to-have items.
- Record the source section for each requirement when identifiable.
- Acceptance criteria must be testable statements.

## Original Task

<ORIGINAL_TASK>
{{ task_text }}
</ORIGINAL_TASK>

## Response format

Reply with a short Markdown summary, then EXACTLY ONE status block in this
form (JSON must validate; no other `<AI_COUNCIL_STATUS>` block may appear):

<AI_COUNCIL_STATUS>
{
  "role": "extractor",
  "requirements": [
    {
      "id": "REQ-001",
      "text": "...",
      "source": {"file": "{{ task_file }}", "section": "..."},
      "priority": "MUST",
      "status": "OPEN",
      "covered_by": [],
      "validation": []
    }
  ],
  "acceptance_criteria": [
    {"id": "AC-001", "text": "...", "status": "OPEN", "evidence": []}
  ]
}
</AI_COUNCIL_STATUS>
