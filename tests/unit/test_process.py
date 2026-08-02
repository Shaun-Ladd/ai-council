import sys
import time

from ai_council.adapters.process import build_env, run_process


def test_run_simple_command():
    result = run_process([sys.executable, "-c", "print('hello')"], timeout_seconds=30)
    assert result.ok
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"


def test_stdin_passed():
    result = run_process(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
        stdin_text="prompt text", timeout_seconds=30,
    )
    assert "PROMPT TEXT" in result.stdout


def test_nonzero_exit_and_stderr():
    result = run_process(
        [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
        timeout_seconds=30,
    )
    assert not result.ok
    assert result.exit_code == 3
    assert "boom" in result.stderr


def test_timeout_kills_process():
    start = time.monotonic()
    result = run_process(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout_seconds=1
    )
    assert result.timed_out
    assert not result.ok
    assert time.monotonic() - start < 10


def test_executable_not_found():
    result = run_process(["definitely-not-a-real-binary-xyz"], timeout_seconds=5)
    assert result.exit_code == 127
    assert "not found" in result.stderr


def test_output_size_cap():
    result = run_process(
        [sys.executable, "-c", "print('x' * 100000)"],
        timeout_seconds=30, max_output_bytes=1000,
    )
    assert result.truncated
    assert len(result.stdout) <= 1000


def test_env_allowlist():
    env = build_env(["PATH"], environ={"PATH": "/usr/bin", "SECRET_TOKEN": "leak"})
    assert env == {"PATH": "/usr/bin"}
    result = run_process(
        [sys.executable, "-c", "import os; print(os.environ.get('SECRET_TOKEN', 'ABSENT'))"],
        timeout_seconds=30, env=build_env(["PATH", "HOME"]),
    )
    assert "ABSENT" in result.stdout
