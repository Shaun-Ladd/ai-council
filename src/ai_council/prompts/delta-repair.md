# AI Council — Solution Architect: Edit Application Failed

You are the Solution Architect. Your previous revision used SEARCH/REPLACE
edit blocks, but they could not be applied to the current proposal:

```
{{ patch_error }}
```

Current proposal (authoritative version and hash — your SEARCH text must be
copied from THIS document exactly):

PROPOSAL-VERSION: {{ proposal_version }}
PROPOSAL-HASH: {{ proposal_hash }}

<CURRENT_PROPOSAL>
{{ proposal_text }}
</CURRENT_PROPOSAL>

## Your previous response (for reference)

<PREVIOUS_RESPONSE>
{{ previous_response }}
</PREVIOUS_RESPONSE>

## What to do

Keep your substantive changes the same — only fix the edit application:

1. Resend corrected edit blocks whose SEARCH text is copied EXACTLY,
   character for character, from the current proposal above and is unique
   within it, OR
2. Send the COMPLETE new proposal document as the response body instead.

End with EXACTLY ONE status block (same schema as before):

<AI_COUNCIL_STATUS>
{
  "role": "architect",
  "decision": "REVISED",
  "proposal_version": {{ proposal_version }},
  "proposal_hash": "{{ proposal_hash }}",
  "confidence": 0.0,
  "summary": "...",
  "material_change": true,
  "finding_responses": [],
  "human_questions": [],
  "unresolved_objections": []
}
</AI_COUNCIL_STATUS>
