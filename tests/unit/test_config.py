from pathlib import Path

import pytest

from ai_council.config import CouncilConfig, deep_merge, load_config


def test_defaults():
    cfg = CouncilConfig()
    assert cfg.session.maxDebateRounds == 15
    assert cfg.session.maxJudgeCycles == 3
    assert cfg.agreement.minimumConfidence == 0.85
    assert cfg.workspace.mode == "read-only"
    assert cfg.agents.architect.adapter == "claude-code"
    assert cfg.agents.reviewer.adapter == "codex"
    assert "PATH" in cfg.security.allowedEnvironmentVariables


def test_deep_merge_nested_and_lists():
    base = {"a": {"b": 1, "c": [1, 2]}, "d": 4}
    override = {"a": {"c": [9]}, "e": 5}
    merged = deep_merge(base, override)
    assert merged == {"a": {"b": 1, "c": [9]}, "d": 4, "e": 5}
    assert base["a"]["c"] == [1, 2]  # base not mutated


def test_layered_priority(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config" / "ai-council").mkdir(parents=True)
    (home / ".config" / "ai-council" / "config.yaml").write_text(
        "session:\n  maxDebateRounds: 3\n  maxJudgeCycles: 9\n"
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "ai-council.yaml").write_text("session:\n  maxDebateRounds: 5\n")

    cfg = load_config(repo_root=repo)
    assert cfg.session.maxDebateRounds == 5      # repo beats user
    assert cfg.session.maxJudgeCycles == 9       # user beats defaults

    cfg = load_config(repo_root=repo, cli_overrides={"session": {"maxDebateRounds": 1}})
    assert cfg.session.maxDebateRounds == 1      # CLI beats repo


def test_repo_config_dir_beats_top_level(tmp_path: Path):
    repo = tmp_path
    (repo / ".ai-council").mkdir()
    (repo / ".ai-council" / "config.yaml").write_text("session:\n  maxDebateRounds: 2\n")
    (repo / "ai-council.yaml").write_text("session:\n  maxDebateRounds: 7\n")
    cfg = load_config(repo_root=repo)
    assert cfg.session.maxDebateRounds == 2


def test_explicit_config_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(repo_root=tmp_path, explicit_path=tmp_path / "nope.yaml")


def test_unknown_keys_rejected():
    with pytest.raises(Exception):
        CouncilConfig.model_validate({"sessionn": {}})
