"""End-to-end CLI tests using config-file-driven mock adapters."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from ai_council.cli import app
from council_fixtures import (
    PROPOSAL_V1,
    TASK_TEXT,
    approve_judge,
    architect_agree_response,
    architect_proposal_response,
    extraction,
    reviewer_response,
)

runner = CliRunner()


def _write_mock_repo(repo: Path) -> Path:
    """Repo with a config that runs a full approved session on mock adapters."""
    repo.mkdir(exist_ok=True)
    scripts = {
        "extractor.yaml": [{"response": extraction()}],
        "architect.yaml": [
            {"response": architect_proposal_response(PROPOSAL_V1)},
            {"response": architect_agree_response()},
        ],
        "reviewer.yaml": [{"response": reviewer_response("APPROVE_FOR_JUDGE", confidence=0.95)}],
        "judge.yaml": [{"response": approve_judge()}],
    }
    for name, script in scripts.items():
        (repo / name).write_text(yaml.safe_dump({"responses": script}))
    config = {
        "agents": {
            "architect": {"adapter": "mock", "script": str(repo / "architect.yaml")},
            "reviewer": {"adapter": "mock", "script": str(repo / "reviewer.yaml")},
            "judge": {"adapter": "mock", "script": str(repo / "judge.yaml")},
            "extractor": {"adapter": "mock", "script": str(repo / "extractor.yaml")},
        }
    }
    (repo / "ai-council.yaml").write_text(yaml.safe_dump(config))
    (repo / "TASK.md").write_text(TASK_TEXT)
    return repo


def test_discuss_and_inspection_commands(tmp_path: Path):
    repo = _write_mock_repo(tmp_path / "repo")

    result = runner.invoke(
        app, ["discuss", str(repo / "TASK.md"), "--repo", str(repo)]
    )
    assert result.exit_code == 0, result.output
    assert "APPROVED" in result.output

    sessions = list((repo / ".ai-council" / "sessions").iterdir())
    assert len(sessions) == 1
    sid = sessions[0].name

    result = runner.invoke(app, ["status", sid, "--repo", str(repo)])
    assert result.exit_code == 0
    assert "APPROVED" in result.output

    result = runner.invoke(app, ["list", "--repo", str(repo)])
    assert sid in result.output

    result = runner.invoke(app, ["proposal", sid, "--repo", str(repo)])
    assert "Widget Importer" in result.output

    result = runner.invoke(app, ["judgment", sid, "--repo", str(repo)])
    assert result.exit_code == 0

    result = runner.invoke(app, ["transcript", sid, "--repo", str(repo)])
    assert "AI Council Transcript" in result.output

    out_file = tmp_path / "export.json"
    result = runner.invoke(
        app, ["export", sid, "--format", "json", "--output", str(out_file),
              "--repo", str(repo)]
    )
    assert result.exit_code == 0
    exported = json.loads(out_file.read_text())
    assert exported["final_report"]["approved_by_judge"] is True

    result = runner.invoke(app, ["export", sid, "--repo", str(repo)])
    assert "Final Report" in result.output

    # convenience copies exist at the .ai-council root
    assert (repo / ".ai-council" / "final-plan.md").is_file()
    assert (repo / ".ai-council" / "proposal.md").is_file()


def test_validate_config(tmp_path: Path):
    repo = _write_mock_repo(tmp_path / "repo")
    result = runner.invoke(app, ["validate-config", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "valid" in result.output

    (repo / "ai-council.yaml").write_text("session:\n  maxDebateRoundz: 5\n")
    result = runner.invoke(app, ["validate-config", "--repo", str(repo)])
    assert result.exit_code == 1


def test_doctor_with_mock_agents(tmp_path: Path):
    repo = _write_mock_repo(tmp_path / "repo")
    result = runner.invoke(app, ["doctor", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_quiet_mode(tmp_path: Path):
    repo = _write_mock_repo(tmp_path / "repo2")
    result = runner.invoke(
        app, ["discuss", str(repo / "TASK.md"), "--repo", str(repo), "--quiet"]
    )
    assert result.exit_code == 0
    assert "[state]" not in result.output
