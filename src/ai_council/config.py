"""Layered YAML configuration.

Priority (highest wins):
    1. command-line overrides
    2. repository config (./ai-council.yaml, ./.ai-council/config.yaml)
    3. user config (~/.config/ai-council/config.yaml)
    4. built-in defaults
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field


class SessionLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    maxDebateRounds: int = 8
    maxJudgeCycles: int = 3
    maxFormatRetries: int = 2
    maxAgentFailures: int = 2
    repeatedDisagreementLimit: int = 2
    saveRawLogs: bool = True
    archiveEveryRound: bool = True
    resumable: bool = True


class AgreementConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimumConfidence: float = 0.85
    requireMatchingProposalHash: bool = True
    requireNoBlockingFindings: bool = True


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter: str = "mock"
    model: str = "default"
    timeoutSeconds: int = 900
    isolatedContext: bool = False
    command: Optional[str] = None          # override executable path
    extraArgs: list[str] = Field(default_factory=list)
    # mock adapter only: path to a script file, or inline scripted responses
    script: Optional[str] = None
    responses: list[dict[str, Any]] = Field(default_factory=list)


class JudgePanelMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    adapter: str
    model: str = "default"
    timeoutSeconds: int = 900


class JudgesConfig(BaseModel):
    """Multi-judge panel configuration (only `single` is implemented today,
    but the shape supports quorum/majority/unanimous later)."""
    model_config = ConfigDict(extra="forbid")
    mode: str = "single"  # single | unanimous | majority | quorum
    requiredApprovals: int = 1
    agents: list[JudgePanelMember] = Field(default_factory=list)


class AgentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    architect: AgentConfig = Field(default_factory=lambda: AgentConfig(adapter="claude-code"))
    reviewer: AgentConfig = Field(default_factory=lambda: AgentConfig(adapter="codex"))
    judge: AgentConfig = Field(default_factory=lambda: AgentConfig(adapter="codex", isolatedContext=True))
    extractor: Optional[AgentConfig] = None  # defaults to architect's adapter


class WorkspaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = "read-only"  # read-only | worktree | direct-write
    root: str = "."
    allowCommands: bool = False


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    console: bool = True
    markdownReport: bool = True
    jsonReport: bool = True
    htmlTranscript: bool = False


class SecurityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    redactEnvironmentVariables: bool = True
    allowedEnvironmentVariables: list[str] = Field(default_factory=lambda: ["PATH", "HOME"])
    maximumCapturedOutputBytes: int = 2_000_000


class CouncilConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    session: SessionLimits = Field(default_factory=SessionLimits)
    agreement: AgreementConfig = Field(default_factory=AgreementConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    judges: Optional[JudgesConfig] = None
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` on top of ``base``. Lists are replaced,
    not concatenated, so higher layers fully control list-valued settings."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping")
    return data


def user_config_path() -> Path:
    return Path.home() / ".config" / "ai-council" / "config.yaml"


def repo_config_paths(repo_root: Path) -> list[Path]:
    return [repo_root / ".ai-council" / "config.yaml", repo_root / "ai-council.yaml"]


def load_config(
    repo_root: Path | str = ".",
    explicit_path: Path | str | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> CouncilConfig:
    """Build the effective configuration from all layers."""
    repo_root = Path(repo_root)
    merged: dict[str, Any] = {}
    merged = deep_merge(merged, _load_yaml(user_config_path()))
    if explicit_path is not None:
        explicit = Path(explicit_path)
        if not explicit.is_file():
            raise FileNotFoundError(f"Config file not found: {explicit}")
        merged = deep_merge(merged, _load_yaml(explicit))
    else:
        for candidate in repo_config_paths(repo_root):
            layer = _load_yaml(candidate)
            if layer:
                merged = deep_merge(merged, layer)
                break
    if cli_overrides:
        merged = deep_merge(merged, cli_overrides)
    return CouncilConfig.model_validate(merged)
