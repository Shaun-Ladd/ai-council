"""Safe subprocess execution for agent CLIs.

Guarantees:
- argv arrays only; ``shell=True`` is never used
- environment allowlist (plus explicitly provided extra variables)
- wall-clock timeout with process-group kill
- stdout/stderr capture with a maximum-size cap
- exit-code capture; cancellation (KeyboardInterrupt) handling
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

from .base import InvocationResult


def build_env(
    allowlist: list[str],
    extra: Optional[dict[str, str]] = None,
    environ: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    source = environ if environ is not None else dict(os.environ)
    env = {k: source[k] for k in allowlist if k in source}
    if extra:
        env.update(extra)
    return env


def run_process(
    argv: list[str],
    *,
    stdin_text: str = "",
    timeout_seconds: int = 900,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
    max_output_bytes: int = 2_000_000,
) -> InvocationResult:
    """Run ``argv`` and capture the outcome. Never raises for process
    failure; returns a populated :class:`InvocationResult` instead."""
    start = time.monotonic()
    result = InvocationResult(argv=list(argv))
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv array, no shell
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=env,
            start_new_session=True,  # own process group so we can kill children
        )
    except FileNotFoundError as exc:
        result.stderr = f"Executable not found: {argv[0]} ({exc})"
        result.exit_code = 127
        result.duration_seconds = time.monotonic() - start
        return result
    except OSError as exc:
        result.stderr = f"Failed to start process: {exc}"
        result.exit_code = 126
        result.duration_seconds = time.monotonic() - start
        return result

    def _kill() -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()

    try:
        stdout_b, stderr_b = proc.communicate(
            input=stdin_text.encode("utf-8"), timeout=timeout_seconds
        )
        result.exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        _kill()
        stdout_b, stderr_b = proc.communicate()
        result.timed_out = True
        result.exit_code = proc.returncode
    except KeyboardInterrupt:
        _kill()
        stdout_b, stderr_b = proc.communicate()
        result.cancelled = True
        result.exit_code = proc.returncode
        result.duration_seconds = time.monotonic() - start
        result.stdout, result.stderr = _decode_capped(stdout_b, stderr_b, max_output_bytes, result)
        raise ProcessCancelled(result)

    result.duration_seconds = time.monotonic() - start
    result.stdout, result.stderr = _decode_capped(stdout_b, stderr_b, max_output_bytes, result)
    return result


def _decode_capped(
    stdout_b: bytes, stderr_b: bytes, max_bytes: int, result: InvocationResult
) -> tuple[str, str]:
    if len(stdout_b) > max_bytes:
        stdout_b = stdout_b[:max_bytes]
        result.truncated = True
    if len(stderr_b) > max_bytes:
        stderr_b = stderr_b[:max_bytes]
        result.truncated = True
    return (
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


class ProcessCancelled(Exception):
    """Raised when the user interrupts a running agent process."""

    def __init__(self, result: InvocationResult):
        super().__init__("Agent process cancelled by user")
        self.result = result
