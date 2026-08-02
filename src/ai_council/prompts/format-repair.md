# AI Council — Response Format Repair

Your previous response could not be processed because its structured status
block was missing or invalid. This retry is about FORMAT ONLY — keep your
substantive content and decision the same.
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

## Your previous response

<PREVIOUS_RESPONSE>
{{ previous_response }}
</PREVIOUS_RESPONSE>

## What to do

Resend your COMPLETE response (Markdown body plus status block), corrected so
that it contains EXACTLY ONE block of the form:

<AI_COUNCIL_STATUS>
{ ...valid JSON matching the {{ role }} schema... }
</AI_COUNCIL_STATUS>

Requirements:
- The JSON must be a single object, valid JSON (double-quoted keys/strings,
  no trailing commas, no comments).
- `"role"` must be "{{ role }}".
- Do not include any other `<AI_COUNCIL_STATUS>` block anywhere.
- Do not change your substantive decision or content — only fix the format.
