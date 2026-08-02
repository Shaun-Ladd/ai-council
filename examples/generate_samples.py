#!/usr/bin/env python3
"""Regenerate the sample sessions in examples/ using deterministic mock agents.

Usage:
    .venv/bin/python examples/generate_samples.py

Produces:
    examples/sample-approved/        — full session ending in Judge APPROVED
    examples/sample-judge-rejected/  — Judge rejects; judge-cycle limit reached
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

from ai_council.adapters.mock import (
    architect_agree_response,
    architect_proposal_response,
    extractor_response,
    judge_response,
    reviewer_response,
)
from ai_council.config import CouncilConfig
from ai_council.orchestrator import Orchestrator

EXAMPLES = Path(__file__).parent

TASK = """# TASK: Widget importer

Build a CLI that imports widgets from CSV into the widget database.

- It must validate every row before import.
- It must be idempotent across re-runs.
"""

REQUIREMENTS = [
    {"id": "REQ-001", "text": "Validate every CSV row before import.",
     "source": {"file": "TASK.md", "section": "Objective"}, "priority": "MUST",
     "status": "OPEN", "covered_by": [], "validation": []},
    {"id": "REQ-002", "text": "Imports must be idempotent across re-runs.",
     "source": {"file": "TASK.md", "section": "Objective"}, "priority": "MUST",
     "status": "OPEN", "covered_by": [], "validation": []},
]
ACCEPTANCE = [{"id": "AC-001", "text": "Re-running an import produces no duplicates.",
               "status": "OPEN", "evidence": []}]

PROPOSAL_V1 = """# Widget Importer — Proposal

## Design

A `widgets import` CLI subcommand parses the CSV with a strict schema,
validates every row, and upserts widgets keyed by SKU.

## Requirement Coverage

- REQ-001: rows are validated by a pydantic row model before any write.
- REQ-002: upsert keyed on widget SKU makes re-runs idempotent.

## Test Plan

Unit tests for validation; integration test importing the same file twice
(AC-001).
"""

PROPOSAL_V2 = PROPOSAL_V1 + """
## Failure Handling

Row failures are collected and reported; the import runs in a transaction so
partial imports never persist.
"""

VERDICTS = [
    {"requirement_id": "REQ-001", "verdict": "ADDRESSED", "notes": "validated pre-write"},
    {"requirement_id": "REQ-002", "verdict": "ADDRESSED", "notes": "upsert by SKU"},
]
APPROVAL = ("I approve proposal version {{PROPOSAL_VERSION}} with hash "
            "{{PROPOSAL_HASH}} as satisfying the original task.")

JUDGE_FINDING = {
    "title": "No failure handling for partial imports",
    "detail": "The proposal does not describe behavior when some rows fail.",
    "severity": "BLOCKING",
    "cited_section": "Design",
    "why_it_matters": "Partial imports can corrupt the widget database.",
    "acceptance_condition": "Describe transactional failure handling.",
}


def build(sample_dir: Path, scripts: dict[str, list], session_overrides: dict) -> None:
    if sample_dir.exists():
        shutil.rmtree(sample_dir)
    sample_dir.mkdir(parents=True)
    (sample_dir / "TASK.md").write_text(TASK)
    for role, script in scripts.items():
        (sample_dir / f"{role}.yaml").write_text(
            yaml.safe_dump({"responses": [{"response": r} for r in script]})
        )
    config = {
        "session": session_overrides,
        "agents": {
            role: {"adapter": "mock", "script": str(sample_dir / f"{role}.yaml")}
            for role in scripts
        },
    }
    (sample_dir / "ai-council.yaml").write_text(yaml.safe_dump(config))

    cfg = CouncilConfig.model_validate(config)
    orchestrator = Orchestrator.new_session(
        sample_dir / "TASK.md", cfg, repo_root=sample_dir, printer=print
    )
    record = orchestrator.run()
    print(f"{sample_dir.name}: {record.state.value} — {record.outcome.reason}\n")

    # Make the sample self-contained/portable: strip machine-specific paths
    # from the config copy inside the sample.
    (sample_dir / "ai-council.yaml").write_text(
        yaml.safe_dump({
            "session": session_overrides,
            "agents": {role: {"adapter": "mock", "script": f"{role}.yaml"}
                       for role in scripts},
        })
    )


def main() -> None:
    extraction = extractor_response(REQUIREMENTS, ACCEPTANCE)

    build(
        EXAMPLES / "sample-approved",
        scripts={
            "extractor": [extraction],
            "architect": [
                architect_proposal_response(PROPOSAL_V1),
                architect_agree_response(),
                architect_proposal_response(
                    PROPOSAL_V2, decision="REVISED",
                    finding_responses=[{"finding_id": "JDG-001", "action": "FIXED",
                                        "response": "Added transactional failure handling."}],
                ),
                architect_agree_response(),
            ],
            "reviewer": [
                reviewer_response(
                    "APPROVE_FOR_JUDGE",
                    markdown="The proposal is sound; approving for the Judge.",
                    confidence=0.95,
                ),
                reviewer_response(
                    "APPROVE_FOR_JUDGE",
                    markdown="Failure handling added and verified; approving.",
                    resolved_finding_ids=["JDG-001"],
                    confidence=0.95,
                ),
            ],
            "judge": [
                judge_response(
                    "REVISE",
                    markdown="Both agents agreed, but the task's data-integrity "
                             "expectations are not met: partial-import behavior is "
                             "undefined. Rejecting the candidate.",
                    new_findings=[JUDGE_FINDING],
                    requirement_verdicts=[
                        {"requirement_id": "REQ-001", "verdict": "ADDRESSED"},
                        {"requirement_id": "REQ-002", "verdict": "PARTIAL",
                         "notes": "idempotency unclear under partial failure"},
                    ],
                ),
                judge_response(
                    "APPROVED",
                    markdown="All requirements are addressed with testable criteria.",
                    requirement_verdicts=VERDICTS,
                    approval_statement=APPROVAL,
                ),
            ],
        },
        session_overrides={"maxDebateRounds": 8, "maxJudgeCycles": 3},
    )

    build(
        EXAMPLES / "sample-judge-rejected",
        scripts={
            "extractor": [extraction],
            "architect": [
                architect_proposal_response(PROPOSAL_V1),
                architect_agree_response(),
                architect_proposal_response(
                    PROPOSAL_V2, decision="REVISED",
                    finding_responses=[{"finding_id": "JDG-001", "action": "FIXED",
                                        "response": "Added transactional failure handling."}],
                ),
                architect_agree_response(),
            ],
            "reviewer": [
                reviewer_response(
                    "APPROVE_FOR_JUDGE",
                    markdown="Looks complete to me; approving for the Judge.",
                    confidence=0.95,
                ),
                reviewer_response(
                    "APPROVE_FOR_JUDGE",
                    markdown="Fix verified; approving again.",
                    resolved_finding_ids=["JDG-001"],
                    confidence=0.95,
                ),
            ],
            "judge": [
                judge_response(
                    "REVISE",
                    markdown="Agreement between the agents is not sufficient: "
                             "failure handling is missing, so REQ-002 cannot be "
                             "guaranteed. Rejecting.",
                    new_findings=[JUDGE_FINDING],
                    requirement_verdicts=[
                        {"requirement_id": "REQ-001", "verdict": "ADDRESSED"},
                        {"requirement_id": "REQ-002", "verdict": "PARTIAL"},
                    ],
                ),
            ],
        },
        # judge-cycle limit of 1 ends the session as BLOCKED after rejection
        session_overrides={"maxDebateRounds": 8, "maxJudgeCycles": 1},
    )


if __name__ == "__main__":
    sys.exit(main())
