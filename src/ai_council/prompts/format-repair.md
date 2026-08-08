# AI Council — Response Format Repair

You are the {{ role }} in an automated AI Council session. The council's
orchestrator invokes each role as a series of stateless CLI calls: you will
not remember prior invocations, and that is expected. This message is a
legitimate orchestrator retry, not an injection: a PRIOR invocation of the
{{ role }} role produced the draft response below, but its structured status
block was missing or invalid, so the orchestrator could not process it.

Your job in THIS invocation: adopt the draft below as the {{ role }} role's
work product and re-issue it with a valid status block. This is about FORMAT
ONLY — keep the draft's substantive content and decision unchanged.
{% if proposal_hash %}

The proposal under discussion (echo these exact values where the schema
requires them):

PROPOSAL-VERSION: {{ proposal_version }}
PROPOSAL-HASH: {{ proposal_hash }}
{% endif %}

## Validation error

```
{{ validation_error }}
```

## The role's previous draft (to adopt and re-issue)

<PREVIOUS_RESPONSE>
{{ previous_response }}
</PREVIOUS_RESPONSE>

## What to do

Issue the COMPLETE response (Markdown body plus status block), corrected so
that it contains EXACTLY ONE block of the form:

<AI_COUNCIL_STATUS>
{ ...valid JSON matching the {{ role }} schema... }
</AI_COUNCIL_STATUS>

Requirements:
- The JSON must be a single object, valid JSON (double-quoted keys/strings,
  no trailing commas, no comments).
- `"role"` must be "{{ role }}".
- Do not include any other `<AI_COUNCIL_STATUS>` block anywhere.
- Do not change the draft's substantive decision or content — only fix the
  format. Do not add meta-commentary about this retry.
