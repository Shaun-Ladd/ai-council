"""Transcript persistence: append-only JSONL plus a readable Markdown log."""
from __future__ import annotations

import itertools
from typing import Optional

from .models import TranscriptEvent
from .storage import SessionStore, append_jsonl


class Transcript:
    def __init__(self, store: SessionStore):
        self.store = store
        self._counter = itertools.count(self._existing_event_count() + 1)

    def _existing_event_count(self) -> int:
        path = self.store.transcript_jsonl
        if not path.is_file():
            return 0
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)

    def next_event_id(self) -> str:
        return f"EVT-{next(self._counter):05d}"

    def record(self, event: TranscriptEvent) -> None:
        append_jsonl(self.store.transcript_jsonl, event.model_dump(mode="json"))
        self._append_markdown(event)

    def _append_markdown(self, event: TranscriptEvent) -> None:
        path = self.store.transcript_md
        if not path.is_file():
            header = f"# AI Council Transcript — session {event.session_id}\n"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(header, encoding="utf-8")
        lines = [
            "",
            f"## {event.event_id} · {event.timestamp} · {event.kind}",
            "",
            f"- round: {event.round}, judge cycle: {event.judge_cycle}",
        ]
        if event.role:
            lines.append(f"- agent: {event.agent} ({event.role})")
        if event.invocation_id:
            lines.append(f"- invocation: {event.invocation_id} (retries: {event.retry_count})")
        if event.prompt_name:
            lines.append(f"- prompt: {event.prompt_name} ({event.prompt_hash[:12]})")
        if event.proposal_version:
            lines.append(
                f"- proposal: v{event.proposal_version:03d} ({event.proposal_hash[:12]})"
            )
        if event.parsed_decision:
            lines.append(f"- decision: **{event.parsed_decision}**")
        if event.exit_code is not None:
            lines.append(f"- exit code: {event.exit_code}, duration: {event.duration_seconds:.1f}s")
        if event.response_path:
            lines.append(f"- response: `{event.response_path}`")
        if event.detail:
            lines.append("")
            lines.append(event.detail)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # -- convenience ------------------------------------------------------
    def note(
        self,
        session_id: str,
        detail: str,
        *,
        kind: str = "note",
        round_no: int = 0,
        judge_cycle: int = 0,
        role: str = "",
        agent: str = "",
        parsed_decision: str = "",
    ) -> None:
        self.record(
            TranscriptEvent(
                event_id=self.next_event_id(),
                session_id=session_id,
                kind=kind,
                round=round_no,
                judge_cycle=judge_cycle,
                role=role,
                agent=agent,
                parsed_decision=parsed_decision,
                detail=detail,
            )
        )
