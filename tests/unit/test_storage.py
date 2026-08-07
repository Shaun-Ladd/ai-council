import json
from pathlib import Path

import pytest

from ai_council.hashing import sha256_text
from ai_council.models import SessionRecord
from ai_council.storage import (
    ImmutableArtifactError,
    SessionStore,
    atomic_write_text,
    find_session,
    list_sessions,
    new_session_id,
    write_immutable,
)


def test_atomic_write_and_no_temp_residue(tmp_path: Path):
    target = tmp_path / "sub" / "file.txt"
    atomic_write_text(target, "hello")
    assert target.read_text() == "hello"
    atomic_write_text(target, "world")
    assert target.read_text() == "world"
    assert [p.name for p in target.parent.iterdir()] == ["file.txt"]


def test_immutable_refuses_overwrite(tmp_path: Path):
    target = tmp_path / "artifact.md"
    write_immutable(target, "v1")
    with pytest.raises(ImmutableArtifactError):
        write_immutable(target, "v2")
    assert target.read_text() == "v1"


def test_session_id_format():
    sid = new_session_id()
    date, time_, suffix = sid.split("-")
    assert len(date) == 8 and len(time_) == 6 and len(suffix) == 6


def test_session_roundtrip_and_lookup(tmp_path: Path):
    root = tmp_path / ".ai-council"
    sid = new_session_id()
    store = SessionStore(root, sid)
    store.create_layout()
    record = SessionRecord(id=sid, task_hash=sha256_text("task"))
    store.save_session(record)

    assert list_sessions(root) == [sid]
    loaded = find_session(root, sid[:10]).load_session()
    assert loaded.id == sid
    assert loaded.task_hash == record.task_hash

    with pytest.raises(FileNotFoundError):
        find_session(root, "zzz")


def test_hash_generation_stable():
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abd")
    assert len(sha256_text("abc")) == 64


def test_root_convenience_copies(tmp_path: Path):
    root = tmp_path / ".ai-council"
    store = SessionStore(root, "20260801-000000-aaaaaa")
    store.create_layout()
    store.problem_md.write_text("problem")
    store.transcript_md.write_text("transcript")
    proposal = store.proposal_path(1)
    write_immutable(proposal, "proposal body")
    store.refresh_root_copies(latest_proposal=proposal)
    assert (root / "problem.md").read_text() == "problem"
    assert (root / "proposal.md").read_text() == "proposal body"
    status = json.loads((root / "status.json").read_text())
    assert status["latest_session"] == "20260801-000000-aaaaaa"


def test_session_lock_lifecycle(tmp_path: Path):
    import os
    import subprocess

    from ai_council.storage import SessionLockedError

    store = SessionStore(tmp_path / ".ai-council", "20260807-000000-aaaaaa")
    store.create_layout()

    store.acquire_session_lock()
    assert store.lock_path.is_file()
    store.acquire_session_lock()          # reentrant for the same pid
    assert store.session_lock_holder() is None  # own lock is not a foreign holder

    # foreign LIVE holder (parent pid) -> refused
    import json
    store.lock_path.write_text(json.dumps({"pid": os.getppid(), "started_at": "t"}))
    with pytest.raises(SessionLockedError, match="already being run"):
        store.acquire_session_lock()

    # stale holder (dead pid) -> stolen
    dead = subprocess.Popen(["true"]); dead.wait()
    store.lock_path.write_text(json.dumps({"pid": dead.pid, "started_at": "t"}))
    store.acquire_session_lock()
    assert json.loads(store.lock_path.read_text())["pid"] == os.getpid()

    store.release_session_lock()
    assert not store.lock_path.exists()
