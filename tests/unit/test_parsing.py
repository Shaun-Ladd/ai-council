import pytest

from ai_council.models import ArchitectStatus, ReviewerStatus
from ai_council.parsing import (
    StatusParseError,
    extract_status_block,
    parse_status,
    strip_status_block,
)

GOOD = """Here is my proposal.

<AI_COUNCIL_STATUS>
{"role": "architect", "decision": "PROPOSED", "confidence": 0.9, "summary": "s"}
</AI_COUNCIL_STATUS>
"""


def test_extract_single_block():
    raw = extract_status_block(GOOD)
    assert '"decision": "PROPOSED"' in raw


def test_extract_with_code_fence():
    text = "x\n<AI_COUNCIL_STATUS>\n```json\n{\"a\": 1}\n```\n</AI_COUNCIL_STATUS>"
    assert extract_status_block(text) == '{"a": 1}'


def test_missing_block():
    with pytest.raises(StatusParseError, match="No <AI_COUNCIL_STATUS>"):
        extract_status_block("just some text {\"decision\": \"AGREED\"}")


def test_multiple_blocks_rejected():
    text = GOOD + "\n<AI_COUNCIL_STATUS>\n{}\n</AI_COUNCIL_STATUS>"
    with pytest.raises(StatusParseError, match="exactly one"):
        extract_status_block(text)


def test_parse_valid_status():
    status = parse_status(GOOD, ArchitectStatus)
    assert status.decision.value == "PROPOSED"
    assert status.confidence == 0.9


def test_parse_invalid_json():
    text = "<AI_COUNCIL_STATUS>\n{not json}\n</AI_COUNCIL_STATUS>"
    with pytest.raises(StatusParseError, match="not valid JSON"):
        parse_status(text, ArchitectStatus)


def test_parse_schema_mismatch():
    text = '<AI_COUNCIL_STATUS>\n{"role": "architect", "decision": "NOPE"}\n</AI_COUNCIL_STATUS>'
    with pytest.raises(StatusParseError, match="schema"):
        parse_status(text, ArchitectStatus)


def test_parse_wrong_role_schema():
    with pytest.raises(StatusParseError):
        parse_status(GOOD, ReviewerStatus)


def test_extra_fields_rejected():
    text = (
        '<AI_COUNCIL_STATUS>\n{"role": "architect", "decision": "PROPOSED", '
        '"bogus": 1}\n</AI_COUNCIL_STATUS>'
    )
    with pytest.raises(StatusParseError):
        parse_status(text, ArchitectStatus)


def test_strip_status_block():
    assert strip_status_block(GOOD) == "Here is my proposal."
