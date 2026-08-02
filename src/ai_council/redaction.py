"""Secret redaction for everything persisted to transcripts and reports.

Two mechanisms:
1. Pattern-based redaction of well-known secret shapes (API keys, tokens,
   private keys, key=value assignments of sensitive variable names).
2. Value-based redaction of the current process's sensitive environment
   variable values, so a secret echoed verbatim by a subprocess never lands
   in a persisted artifact.
"""
from __future__ import annotations

import os
import re
from typing import Iterable

REDACTED = "[REDACTED]"

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),                      # OpenAI-style keys
    re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),                  # Anthropic keys
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),                       # GitHub PAT
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),                           # AWS access key id
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),               # Slack tokens
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),  # JWT
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(
        r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|CREDENTIAL)[A-Z0-9_]*)"
        r"(\s*[=:]\s*)(\"[^\"]+\"|'[^']+'|\S+)"
    ),
]

_SENSITIVE_ENV_RE = re.compile(r"(?i)(SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|CREDENTIAL|PRIVATE)")


def sensitive_env_values(environ: dict[str, str] | None = None) -> list[str]:
    env = environ if environ is not None else dict(os.environ)
    values = [
        v for k, v in env.items()
        if _SENSITIVE_ENV_RE.search(k) and v and len(v) >= 6
    ]
    # Redact longest values first so substrings don't leave residue.
    return sorted(set(values), key=len, reverse=True)


def redact(text: str, extra_values: Iterable[str] = (), environ: dict[str, str] | None = None) -> str:
    """Redact known secret patterns and sensitive env values from ``text``."""
    if not text:
        return text
    for pattern in _PATTERNS:
        if pattern.groups >= 3:  # key=value style: keep the key, redact the value
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
        else:
            text = pattern.sub(REDACTED, text)
    values = list(extra_values) + sensitive_env_values(environ)
    for value in sorted(set(values), key=len, reverse=True):
        if value:
            text = text.replace(value, REDACTED)
    return text
