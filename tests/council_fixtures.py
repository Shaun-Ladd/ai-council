"""Shared fixtures: scripted mock councils for integration tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_council.adapters.mock import (
    MockAgentAdapter,
    architect_agree_response,
    architect_proposal_response,
    extractor_response,
    judge_response,
    reviewer_response,
)
from ai_council.config import CouncilConfig
from ai_council.orchestrator import Orchestrator

TASK_TEXT = """# TASK: Widget importer

Build a CLI that imports widgets from CSV into the widget database.

- It must validate every row before import.
- It must be idempotent across re-runs.
"""

REQUIREMENTS = [
    {
        "id": "REQ-001",
        "text": "Validate every CSV row before import.",
        "source": {"file": "TASK.md", "section": "Objective"},
        "priority": "MUST",
        "status": "OPEN",
        "covered_by": [],
        "validation": [],
    },
    {
        "id": "REQ-002",
        "text": "Imports must be idempotent across re-runs.",
        "source": {"file": "TASK.md", "section": "Objective"},
        "priority": "MUST",
        "status": "OPEN",
        "covered_by": [],
        "validation": [],
    },
]

ACCEPTANCE = [
    {"id": "AC-001", "text": "Re-running an import produces no duplicates.",
     "status": "OPEN", "evidence": []}
]

PROPOSAL_V1 = """# Widget Importer — Proposal

## Design

A `widgets import` CLI subcommand parses the CSV with a strict schema,
validates rows, and upserts by natural key.

## Requirement Coverage

- REQ-001: rows are validated by a pydantic row model before any write.
- REQ-002: upsert keyed on widget SKU makes re-runs idempotent.

## Test Plan

Unit tests for validation; integration test importing the same file twice
(AC-001).
"""

PROPOSAL_V2 = PROPOSAL_V1 + """
## Failure Handling

Row failures are collected and reported; the import is transactional.
"""

ALL_ADDRESSED = [
    {"requirement_id": "REQ-001", "verdict": "ADDRESSED", "notes": "validated pre-write"},
    {"requirement_id": "REQ-002", "verdict": "ADDRESSED", "notes": "upsert by SKU"},
]

APPROVAL_STATEMENT = (
    "I approve proposal version {{PROPOSAL_VERSION}} with hash {{PROPOSAL_HASH}} "
    "as satisfying the original task."
)


def extraction():
    return extractor_response(REQUIREMENTS, ACCEPTANCE)


def approve_judge(**kw):
    kw.setdefault("requirement_verdicts", ALL_ADDRESSED)
    kw.setdefault("approval_statement", APPROVAL_STATEMENT)
    return judge_response("APPROVED", **kw)


BLOCKING_FINDING = {
    "title": "No failure handling",
    "detail": "The proposal has no failure handling for partial imports.",
    "severity": "BLOCKING",
    "cited_section": "Design",
    "why_it_matters": "Partial imports corrupt the database.",
    "acceptance_condition": "Describe transactional failure handling.",
}


def mock_config(**session_overrides) -> CouncilConfig:
    """Config with all roles on (empty) mock adapters; tests inject adapters."""
    cfg = {
        "agents": {
            "architect": {"adapter": "mock"},
            "reviewer": {"adapter": "mock"},
            "judge": {"adapter": "mock", "isolatedContext": True},
            "extractor": {"adapter": "mock"},
        },
    }
    if session_overrides:
        cfg["session"] = session_overrides
    return CouncilConfig.model_validate(cfg)


@pytest.fixture
def task_file(tmp_path: Path) -> Path:
    path = tmp_path / "TASK.md"
    path.write_text(TASK_TEXT, encoding="utf-8")
    return path


def build_orchestrator(
    task_file: Path,
    tmp_path: Path,
    *,
    architect: list,
    reviewer: list,
    judge: list,
    extractor: list | None = None,
    config: CouncilConfig | None = None,
    loop_last: bool = False,
) -> Orchestrator:
    """New session with directly injected mock adapters (scripts are lists of
    response strings or dict entries)."""
    config = config or mock_config()
    orchestrator = Orchestrator.new_session(task_file, config, repo_root=tmp_path)
    orchestrator._adapters = {
        "extractor": _mock(extractor if extractor is not None else [extraction()], loop_last),
        "architect": _mock(architect, loop_last),
        "reviewer": _mock(reviewer, loop_last),
        "judge": _mock(judge, loop_last),
    }
    return orchestrator


def _mock(script: list, loop_last: bool) -> MockAgentAdapter:
    entries = [e if isinstance(e, dict) else {"response": e} for e in script]
    return MockAgentAdapter(script=entries, loop_last=loop_last)


__all__ = [
    "TASK_TEXT",
    "REQUIREMENTS",
    "ACCEPTANCE",
    "PROPOSAL_V1",
    "PROPOSAL_V2",
    "ALL_ADDRESSED",
    "APPROVAL_STATEMENT",
    "BLOCKING_FINDING",
    "extraction",
    "approve_judge",
    "mock_config",
    "build_orchestrator",
    "architect_proposal_response",
    "architect_agree_response",
    "reviewer_response",
    "judge_response",
]
