"""Isolated git-worktree management for implementation mode.

All code changes happen on a dedicated branch inside
``.ai-council/worktrees/<session-id>/`` — the user's checkout is never
modified, and no destructive git commands are ever issued.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


class WorktreeError(Exception):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(  # noqa: S603 - argv array, no shell
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=120,
    )
    if check and result.returncode != 0:
        raise WorktreeError(
            f"git {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result


def is_git_repo(repo: Path) -> bool:
    try:
        return _git(repo, "rev-parse", "--is-inside-work-tree", check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def create_worktree(repo_root: Path, session_id: str) -> tuple[Path, str]:
    """Create (or reuse) the session worktree; returns (path, branch)."""
    if not is_git_repo(repo_root):
        raise WorktreeError(
            f"{repo_root} is not a git repository; implementation mode requires git."
        )
    if _git(repo_root, "rev-parse", "--verify", "HEAD", check=False).returncode != 0:
        raise WorktreeError("Repository has no commits; implementation mode needs a HEAD.")
    branch = f"ai-council/{session_id}"
    path = repo_root / ".ai-council" / "worktrees" / session_id
    if path.is_dir() and (path / ".git").exists():
        return path, branch  # resume: worktree already exists
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo_root, "worktree", "add", "-b", branch, str(path), "HEAD")
    return path, branch


def compute_diff(worktree: Path) -> str:
    """Full diff of the worktree against its base commit, including new files.

    Everything is staged first (`git add -A`) so untracked files appear in
    the diff; staging inside the isolated worktree has no effect on the
    user's checkout.
    """
    _git(worktree, "add", "-A")
    return _git(worktree, "diff", "--staged").stdout


def diff_stats(worktree: Path) -> str:
    return _git(worktree, "diff", "--staged", "--stat", check=False).stdout.strip()


def run_test_command(worktree: Path, command: str, timeout_seconds: int = 900,
                     max_output: int = 200_000) -> tuple[int, str]:
    """Run the configured test command inside the worktree and capture proof.

    Returns (exit_code, combined output). The command string is split
    shell-style into an argv array; no shell is used.
    """
    argv = shlex.split(command)
    try:
        result = subprocess.run(  # noqa: S603
            argv, cwd=str(worktree), capture_output=True, text=True,
            timeout=timeout_seconds,
        )
        output = (result.stdout + "\n" + result.stderr)[-max_output:]
        return result.returncode, output
    except FileNotFoundError as exc:
        return 127, f"test command not found: {exc}"
    except subprocess.TimeoutExpired:
        return 124, f"test command timed out after {timeout_seconds}s"
