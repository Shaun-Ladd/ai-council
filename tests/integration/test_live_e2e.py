"""Opt-in live end-to-end test against installed `claude` and `codex` CLIs.

Run with:

    AI_COUNCIL_LIVE_E2E=1 .venv/bin/pytest tests/integration/test_live_e2e.py -s

This spends real tokens and can take many minutes; the standard suite never
requires live model access.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AI_COUNCIL_LIVE_E2E") != "1",
    reason="live e2e is opt-in: set AI_COUNCIL_LIVE_E2E=1",
)

LIVE_TASK = """# TASK: Shell alias helper

Design (do not implement) a tiny `alias-helper` CLI that lists, adds, and
removes shell aliases in the user's ~/.zshrc.

- It must never corrupt existing content of ~/.zshrc.
- It must support a dry-run mode.
"""


def test_live_discussion(tmp_path: Path):
    if not shutil.which("claude") or not shutil.which("codex"):
        pytest.skip("claude and codex CLIs must both be installed")

    from ai_council.config import load_config
    from ai_council.models import SessionState
    from ai_council.orchestrator import Orchestrator

    task = tmp_path / "TASK.md"
    task.write_text(LIVE_TASK)
    cfg = load_config(repo_root=tmp_path)  # real defaults: claude + codex
    orchestrator = Orchestrator.new_session(task, cfg, repo_root=tmp_path, printer=print)
    record = orchestrator.run()

    assert record.state in (
        SessionState.APPROVED,
        SessionState.AWAITING_HUMAN,
        SessionState.BLOCKED,
    ), record.outcome.reason
    assert orchestrator.store.transcript_jsonl.is_file()
