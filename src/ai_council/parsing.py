"""Extraction and validation of structured agent responses.

Every agent response must contain exactly one

    <AI_COUNCIL_STATUS>
    { ... JSON ... }
    </AI_COUNCIL_STATUS>

block. We never scan for arbitrary trailing JSON objects.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

STATUS_OPEN = "<AI_COUNCIL_STATUS>"
STATUS_CLOSE = "</AI_COUNCIL_STATUS>"

_BLOCK_RE = re.compile(
    re.escape(STATUS_OPEN) + r"\s*(?:```(?:json)?\s*)?(.*?)(?:```\s*)?" + re.escape(STATUS_CLOSE),
    re.DOTALL,
)


class StatusParseError(Exception):
    """The response's structured block is missing, duplicated, or invalid."""

    def __init__(self, message: str, detail: str = "", missing_block: bool = False):
        super().__init__(message)
        self.detail = detail
        # True when no status block exists at all — usually a refusal or
        # derailed response; callers should re-issue the ORIGINAL prompt
        # rather than ask the agent to "repair" a non-answer.
        self.missing_block = missing_block


def extract_status_block(response_text: str) -> str:
    """Return the raw JSON text of the single status block."""
    matches = _BLOCK_RE.findall(response_text)
    if len(matches) == 0:
        raise StatusParseError(
            f"No {STATUS_OPEN}...{STATUS_CLOSE} block found in the response.",
            missing_block=True,
        )
    if len(matches) > 1:
        raise StatusParseError(
            f"Expected exactly one {STATUS_OPEN} block, found {len(matches)}."
        )
    return matches[0].strip()


def parse_status(response_text: str, model: type[BaseModel]) -> BaseModel:
    """Extract, JSON-parse, and schema-validate the status block."""
    raw = extract_status_block(response_text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StatusParseError("Status block is not valid JSON.", detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise StatusParseError("Status block must be a JSON object.")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise StatusParseError(
            f"Status JSON does not match the {model.__name__} schema.",
            detail=exc.json(indent=2),
        ) from exc


def strip_status_block(response_text: str) -> str:
    """Return the human-readable Markdown portion (status block removed)."""
    return _BLOCK_RE.sub("", response_text).strip()


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()
