# AI Council — Requirement Extraction

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
