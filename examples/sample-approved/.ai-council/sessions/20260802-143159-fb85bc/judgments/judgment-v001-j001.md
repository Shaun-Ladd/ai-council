Both agents agreed, but the task's data-integrity expectations are not met: partial-import behavior is undefined. Rejecting the candidate.

<AI_COUNCIL_STATUS>
{
  "role": "judge",
  "decision": "REVISE",
  "proposal_version": 1,
  "proposal_hash": "b25ccd0834c6b3f01bd0cf9f4cbc8d13d67888bee6180e14314b0263790ea0b3",
  "confidence": 0.9,
  "summary": "Both agents agreed, but the task's data-integrity expectations are not met: partial-import behavior is undefined. Rejecting the candidate.",
  "approval_statement": "",
  "requirement_verdicts": [
    {
      "requirement_id": "REQ-001",
      "verdict": "ADDRESSED"
    },
    {
      "requirement_id": "REQ-002",
      "verdict": "PARTIAL",
      "notes": "idempotency unclear under partial failure"
    }
  ],
  "new_findings": [
    {
      "title": "No failure handling for partial imports",
      "detail": "The proposal does not describe behavior when some rows fail.",
      "severity": "BLOCKING",
      "cited_section": "Design",
      "why_it_matters": "Partial imports can corrupt the widget database.",
      "acceptance_condition": "Describe transactional failure handling."
    }
  ],
  "evidence_requests": []
}
</AI_COUNCIL_STATUS>
