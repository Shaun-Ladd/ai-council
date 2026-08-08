"""Adapter for the Claude Code CLI (`claude`).

Invocation model: non-interactive print mode with the prompt on stdin:

    claude -p --output-format text [--model MODEL] [extraArgs...]

In read-only mode the agent is run with ``--permission-mode plan`` so it
cannot modify the repository. Exact flags can be adjusted per-installation
via ``extraArgs`` / ``command`` in the agent configuration.
"""
from __future__ import annotations

import shutil

from ..config import AgentConfig, SecurityConfig
from .base import AgentAdapter, InvocationRequest, InvocationResult
from .process import build_env, run_process


class ClaudeCodeAdapter(AgentAdapter):
    name = "claude-code"

    def __init__(self, agent_config: AgentConfig, security: SecurityConfig):
        self.config = agent_config
        self.security = security
        self.executable = agent_config.command or "claude"

    def build_argv(self, request: InvocationRequest) -> list[str]:
        argv = [self.executable, "-p", "--output-format", "text"]
        if request.read_only:
            # Read-only via tool denial. NOT --permission-mode plan: plan
            # mode's interactive persona ("present the plan to the user and
            # await approval") contradicts council autonomy and caused live
            # role refusals.
            argv += ["--disallowedTools", "Bash,Write,Edit,MultiEdit,NotebookEdit"]
        else:
            # Write mode is only ever used inside an isolated git worktree
            # created by implementation mode; the user's checkout is untouched.
            argv += ["--dangerously-skip-permissions"]
        model = request.model_override or self.config.model
        if model and model != "default":
            argv += ["--model", model]
        argv += self.config.extraArgs
        return argv

    def invoke(self, request: InvocationRequest) -> InvocationResult:
        env = build_env(self.security.allowedEnvironmentVariables)
        return run_process(
            self.build_argv(request),
            stdin_text=request.prompt,
            timeout_seconds=request.timeout_seconds or self.config.timeoutSeconds,
            cwd=request.cwd,
            env=env,
            max_output_bytes=self.security.maximumCapturedOutputBytes,
        )

    def doctor(self) -> tuple[bool, str]:
        path = shutil.which(self.executable)
        if not path:
            return False, f"'{self.executable}' not found on PATH"
        return True, f"found at {path}"
