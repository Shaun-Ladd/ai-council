"""Adapter for the OpenAI Codex CLI (`codex`).

Invocation model: non-interactive exec mode with the prompt on stdin:

    codex exec [--sandbox read-only] [--model MODEL] [extraArgs...] -

In read-only mode the Codex sandbox is set to ``read-only`` so the agent
cannot modify the repository. Exact flags can be adjusted per-installation
via ``extraArgs`` / ``command`` in the agent configuration.
"""
from __future__ import annotations

import shutil

from ..config import AgentConfig, SecurityConfig
from .base import AgentAdapter, InvocationRequest, InvocationResult
from .process import build_env, run_process


class CodexAdapter(AgentAdapter):
    name = "codex"

    def __init__(self, agent_config: AgentConfig, security: SecurityConfig):
        self.config = agent_config
        self.security = security
        self.executable = agent_config.command or "codex"

    def build_argv(self, request: InvocationRequest) -> list[str]:
        argv = [self.executable, "exec", "--skip-git-repo-check"]
        if request.read_only:
            argv += ["--sandbox", "read-only"]
        else:
            # Writes are confined to the cwd, which in implementation mode is
            # the session's isolated git worktree.
            argv += ["--sandbox", "workspace-write"]
        model = request.model_override or self.config.model
        if model and model != "default":
            argv += ["--model", model]
        argv += self.config.extraArgs
        argv.append("-")  # read the prompt from stdin
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
