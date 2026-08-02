"""Agent adapters and the adapter factory."""
from __future__ import annotations

from ..config import AgentConfig, SecurityConfig
from .base import AgentAdapter, AgentAdapterError, InvocationRequest, InvocationResult
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter
from .mock import MockAgentAdapter

__all__ = [
    "AgentAdapter",
    "AgentAdapterError",
    "InvocationRequest",
    "InvocationResult",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "MockAgentAdapter",
    "create_adapter",
]


def create_adapter(agent_config: AgentConfig, security: SecurityConfig) -> AgentAdapter:
    """Instantiate the adapter named by ``agent_config.adapter``."""
    name = agent_config.adapter
    if name in ("claude-code", "claude"):
        return ClaudeCodeAdapter(agent_config, security)
    if name == "codex":
        return CodexAdapter(agent_config, security)
    if name == "mock":
        return MockAgentAdapter(
            script=agent_config.responses or None,
            script_path=agent_config.script,
        )
    raise AgentAdapterError(f"Unknown adapter: {name!r} (expected claude-code, codex, or mock)")
