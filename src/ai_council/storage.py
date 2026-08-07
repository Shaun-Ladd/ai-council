"""Session storage: atomic writes, immutable artifacts, directory layout.

Layout (repository-local):

.ai-council/
├── config.yaml            (user-managed; never written by the tool)
├── problem.md ... final-plan.md   (convenience copies of latest session)
├── prompts/               (optional user prompt overrides)
└── sessions/<session-id>/
    ├── session.json
    ├── problem.md
    ├── requirements.json
    ├── transcript.jsonl / transcript.md
    ├── findings.json
    ├── decisions.md
    ├── final-report.md / final-report.json / final-plan.md
    ├── proposals/proposal-vNNN.md
    ├── reviews/review-vNNN-rNNN.md
    ├── judgments/judgment-vNNN-jNNN.md
    ├── evidence/
    └── logs/
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models import SessionRecord


class ImmutableArtifactError(Exception):
    """Raised on an attempt to overwrite an existing immutable artifact."""


class SessionLockedError(Exception):
    """Raised when a session is already being run by another live process."""


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OverflowError:
        return False


def atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (tmp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def write_immutable(path: Path, content: str) -> None:
    """Write an artifact that must never be overwritten."""
    if path.exists():
        raise ImmutableArtifactError(f"Refusing to overwrite immutable artifact: {path}")
    atomic_write_text(path, content)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def new_session_id(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"


class SessionStore:
    """Filesystem paths and persistence for one session."""

    def __init__(self, council_root: Path | str, session_id: str):
        self.council_root = Path(council_root)
        self.session_id = session_id
        self.session_dir = self.council_root / "sessions" / session_id

    # -- directories ------------------------------------------------------
    @property
    def proposals_dir(self) -> Path:
        return self.session_dir / "proposals"

    @property
    def reviews_dir(self) -> Path:
        return self.session_dir / "reviews"

    @property
    def judgments_dir(self) -> Path:
        return self.session_dir / "judgments"

    @property
    def evidence_dir(self) -> Path:
        return self.session_dir / "evidence"

    @property
    def logs_dir(self) -> Path:
        return self.session_dir / "logs"

    # -- files ------------------------------------------------------------
    @property
    def session_json(self) -> Path:
        return self.session_dir / "session.json"

    @property
    def problem_md(self) -> Path:
        return self.session_dir / "problem.md"

    @property
    def requirements_json(self) -> Path:
        return self.session_dir / "requirements.json"

    @property
    def findings_json(self) -> Path:
        return self.session_dir / "findings.json"

    @property
    def decisions_md(self) -> Path:
        return self.session_dir / "decisions.md"

    @property
    def transcript_jsonl(self) -> Path:
        return self.session_dir / "transcript.jsonl"

    @property
    def transcript_md(self) -> Path:
        return self.session_dir / "transcript.md"

    @property
    def final_report_md(self) -> Path:
        return self.session_dir / "final-report.md"

    @property
    def final_report_json(self) -> Path:
        return self.session_dir / "final-report.json"

    @property
    def final_plan_md(self) -> Path:
        return self.session_dir / "final-plan.md"

    @property
    def unresolved_md(self) -> Path:
        return self.session_dir / "unresolved.md"

    @property
    def human_guidance_md(self) -> Path:
        return self.session_dir / "human-guidance.md"

    # -- session lock (one running orchestrator per session) --------------
    @property
    def lock_path(self) -> Path:
        return self.session_dir / "session.lock"

    def session_lock_holder(self) -> Optional[int]:
        """PID of a LIVE foreign process holding this session's lock, else None."""
        if not self.lock_path.is_file():
            return None
        try:
            data = json.loads(self.lock_path.read_text(encoding="utf-8"))
            pid = int(data.get("pid", -1))
        except (ValueError, json.JSONDecodeError):
            return None
        if pid == os.getpid():
            return None
        return pid if _pid_alive(pid) else None

    def acquire_session_lock(self) -> None:
        """Take the session lock; reentrant for the same process, steals
        stale locks from dead processes, refuses live foreign holders."""
        holder = self.session_lock_holder()
        if holder is not None:
            started = ""
            try:
                started = json.loads(self.lock_path.read_text(encoding="utf-8")).get("started_at", "")
            except (ValueError, json.JSONDecodeError, OSError):
                pass
            raise SessionLockedError(
                f"Session {self.session_id} is already being run by process "
                f"{holder}{f' (started {started})' if started else ''}. "
                "Wait for it to finish (or stop it), then retry."
            )
        from .models import utcnow_iso
        atomic_write_json(self.lock_path, {
            "pid": os.getpid(),
            "started_at": utcnow_iso(),
            "host": socket.gethostname(),
        })

    def release_session_lock(self) -> None:
        if not self.lock_path.is_file():
            return
        try:
            data = json.loads(self.lock_path.read_text(encoding="utf-8"))
            if int(data.get("pid", -1)) == os.getpid():
                self.lock_path.unlink()
        except (ValueError, json.JSONDecodeError, OSError):
            pass

    @property
    def impl_dir(self) -> Path:
        return self.session_dir / "implementation"

    def impl_diff_path(self, version: int) -> Path:
        return self.impl_dir / f"impl-v{version:03d}.diff"

    def impl_review_path(self, version: int, review_no: int) -> Path:
        return self.impl_dir / f"impl-review-v{version:03d}-r{review_no:03d}.md"

    def impl_judgment_path(self, version: int, cycle: int) -> Path:
        return self.impl_dir / f"impl-judgment-v{version:03d}-j{cycle:03d}.md"

    @property
    def final_implementation_diff(self) -> Path:
        return self.session_dir / "final-implementation.diff"

    def proposal_path(self, version: int) -> Path:
        return self.proposals_dir / f"proposal-v{version:03d}.md"

    def review_path(self, version: int, review_no: int) -> Path:
        return self.reviews_dir / f"review-v{version:03d}-r{review_no:03d}.md"

    def judgment_path(self, version: int, cycle: int) -> Path:
        return self.judgments_dir / f"judgment-v{version:03d}-j{cycle:03d}.md"

    def raw_log_path(self, invocation_id: str, stream: str) -> Path:
        return self.logs_dir / f"{invocation_id}.{stream}.log"

    # -- lifecycle --------------------------------------------------------
    def create_layout(self) -> None:
        for d in (
            self.session_dir,
            self.proposals_dir,
            self.reviews_dir,
            self.judgments_dir,
            self.impl_dir,
            self.evidence_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def save_session(self, record: SessionRecord) -> None:
        from .models import utcnow_iso

        record.updated_at = utcnow_iso()
        atomic_write_json(self.session_json, record.model_dump(mode="json"))

    def load_session(self) -> SessionRecord:
        data = json.loads(self.session_json.read_text(encoding="utf-8"))
        return SessionRecord.model_validate(data)

    # -- convenience copies at the .ai-council/ root ----------------------
    _ROOT_COPIES = {
        "problem.md": "problem_md",
        "requirements.json": "requirements_json",
        "transcript.md": "transcript_md",
        "decisions.md": "decisions_md",
        "final-plan.md": "final_plan_md",
        "unresolved.md": "unresolved_md",
    }

    def refresh_root_copies(self, latest_proposal: Optional[Path] = None,
                            latest_review: Optional[Path] = None,
                            latest_judgment: Optional[Path] = None) -> None:
        """Copy the latest session artifacts to the .ai-council/ root."""
        self.council_root.mkdir(parents=True, exist_ok=True)
        for target_name, attr in self._ROOT_COPIES.items():
            src: Path = getattr(self, attr)
            if src.is_file():
                shutil.copy2(src, self.council_root / target_name)
        pairs = [
            (latest_proposal, "proposal.md"),
            (latest_review, "review.md"),
            (latest_judgment, "judge-report.md"),
        ]
        for src, name in pairs:
            if src is not None and src.is_file():
                shutil.copy2(src, self.council_root / name)
        status = {
            "latest_session": self.session_id,
            "session_dir": str(self.session_dir),
        }
        atomic_write_json(self.council_root / "status.json", status)


def list_sessions(council_root: Path | str) -> list[str]:
    sessions_dir = Path(council_root) / "sessions"
    if not sessions_dir.is_dir():
        return []
    return sorted(p.name for p in sessions_dir.iterdir() if (p / "session.json").is_file())


def find_session(council_root: Path | str, session_id: str) -> SessionStore:
    """Return a store for ``session_id``, accepting unique prefixes."""
    sessions = list_sessions(council_root)
    matches = [s for s in sessions if s == session_id] or [s for s in sessions if s.startswith(session_id)]
    if not matches:
        raise FileNotFoundError(f"No session matching '{session_id}' under {council_root}/sessions")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous session id '{session_id}': {', '.join(matches)}")
    return SessionStore(council_root, matches[0])
