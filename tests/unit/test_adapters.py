from pathlib import Path

import pytest
import yaml

from ai_council.adapters import create_adapter
from ai_council.adapters.base import AgentAdapterError, InvocationRequest
from ai_council.adapters.claude_code import ClaudeCodeAdapter
from ai_council.adapters.codex import CodexAdapter
from ai_council.adapters.mock import MockAgentAdapter, load_mock_script
from ai_council.config import AgentConfig, SecurityConfig


def _request(read_only=True):
    return InvocationRequest(
        prompt="PROPOSAL-VERSION: 2\nPROPOSAL-HASH: abc123\n\ndo the thing",
        invocation_id="test-1", role="reviewer", read_only=read_only,
    )


def test_factory_dispatch():
    security = SecurityConfig()
    assert isinstance(create_adapter(AgentConfig(adapter="claude-code"), security),
                      ClaudeCodeAdapter)
    assert isinstance(create_adapter(AgentConfig(adapter="codex"), security), CodexAdapter)
    assert isinstance(create_adapter(AgentConfig(adapter="mock"), security), MockAgentAdapter)
    with pytest.raises(AgentAdapterError):
        create_adapter(AgentConfig(adapter="gemini"), security)


def test_claude_argv_read_only_and_model():
    adapter = ClaudeCodeAdapter(
        AgentConfig(adapter="claude-code", model="opus", extraArgs=["--verbose"]),
        SecurityConfig(),
    )
    argv = adapter.build_argv(_request(read_only=True))
    assert argv[0] == "claude"
    assert "--permission-mode" in argv and "plan" in argv
    assert "--model" in argv and "opus" in argv
    assert "--verbose" in argv
    argv_rw = adapter.build_argv(_request(read_only=False))
    assert "--permission-mode" not in argv_rw


def test_codex_argv_sandbox():
    adapter = CodexAdapter(AgentConfig(adapter="codex"), SecurityConfig())
    argv = adapter.build_argv(_request(read_only=True))
    assert argv[:2] == ["codex", "exec"]
    assert "--sandbox" in argv and "read-only" in argv
    assert argv[-1] == "-"
    argv_rw = adapter.build_argv(_request(read_only=False))
    assert "workspace-write" in argv_rw and "read-only" not in argv_rw


def test_claude_write_mode_flag():
    adapter = ClaudeCodeAdapter(AgentConfig(adapter="claude-code"), SecurityConfig())
    argv_rw = adapter.build_argv(_request(read_only=False))
    assert "--dangerously-skip-permissions" in argv_rw
    assert "--dangerously-skip-permissions" not in adapter.build_argv(_request(read_only=True))


def test_command_override():
    adapter = ClaudeCodeAdapter(
        AgentConfig(adapter="claude-code", command="/opt/bin/claude"), SecurityConfig()
    )
    assert adapter.build_argv(_request())[0] == "/opt/bin/claude"


def test_mock_placeholder_substitution():
    adapter = MockAgentAdapter(script=[
        {"response": "v={{PROPOSAL_VERSION}} h={{PROPOSAL_HASH}}"}
    ])
    result = adapter.invoke(_request())
    assert result.stdout == "v=2 h=abc123"


def test_mock_exhaustion_raises():
    adapter = MockAgentAdapter(script=[{"response": "one"}])
    adapter.invoke(_request())
    with pytest.raises(AgentAdapterError, match="exhausted"):
        adapter.invoke(_request())


def test_mock_loop_last():
    adapter = MockAgentAdapter(script=[{"response": "one"}], loop_last=True)
    adapter.invoke(_request())
    assert adapter.invoke(_request()).stdout == "one"


def test_mock_behaviors():
    adapter = MockAgentAdapter(script=[
        {"behavior": "timeout"},
        {"behavior": "fail", "stderr": "crash"},
    ])
    r1 = adapter.invoke(_request())
    assert r1.timed_out and not r1.ok
    r2 = adapter.invoke(_request())
    assert r2.exit_code == 1 and r2.stderr == "crash"


def test_mock_script_file(tmp_path: Path):
    path = tmp_path / "script.yaml"
    path.write_text(yaml.safe_dump({"responses": [{"response": "hello"}]}))
    assert load_mock_script(path) == [{"response": "hello"}]
    adapter = MockAgentAdapter(script_path=path)
    assert adapter.invoke(_request()).stdout == "hello"


def test_model_override_beats_config_model():
    from ai_council.adapters.base import InvocationRequest
    adapter = ClaudeCodeAdapter(
        AgentConfig(adapter="claude-code", model="sonnet"), SecurityConfig()
    )
    base = InvocationRequest(prompt="p", invocation_id="i", role="architect")
    argv = adapter.build_argv(base)
    assert "sonnet" in argv
    escalated = InvocationRequest(prompt="p", invocation_id="i", role="architect",
                                  model_override="opus")
    argv = adapter.build_argv(escalated)
    assert "opus" in argv and "sonnet" not in argv
