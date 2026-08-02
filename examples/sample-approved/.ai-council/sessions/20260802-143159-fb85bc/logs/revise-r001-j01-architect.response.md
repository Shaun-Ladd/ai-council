# Widget Importer — Proposal

## Design

A `widgets import` CLI subcommand parses the CSV with a strict schema,
validates every row, and upserts widgets keyed by SKU.

## Requirement Coverage

- REQ-001: rows are validated by a pydantic row model before any write.
- REQ-002: upsert keyed on widget SKU makes re-runs idempotent.

## Test Plan

Unit tests for validation; integration test importing the same file twice
(AC-001).

## Failure Handling

Row failures are collected and reported; the import runs in a transaction so
partial imports never persist.


<AI_COUNCIL_STATUS>
{
  "role": "architect",
  "decision": "REVISED",
  "confidence": 0.9,
  "summary": "Initial proposal.",
  "material_change": true,
  "finding_responses": [
    {
      "finding_id": "JDG-001",
      "action": "FIXED",
      "response": "Added transactional failure handling."
    }
  ],
  "human_questions": []
}
</AI_COUNCIL_STATUS>
