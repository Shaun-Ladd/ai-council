"""Evidence system: content-addressed artifacts with metadata.

The system records evidence only for commands/outputs that actually ran;
it never fabricates results. In discussion mode evidence is typically
requirement traceability or documents supplied by the architect.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .hashing import sha256_text
from .models import EvidenceItem
from .storage import SessionStore, atomic_write_json, write_immutable


class EvidenceStore:
    def __init__(self, store: SessionStore):
        self.store = store
        self.index_path = store.evidence_dir / "index.json"
        self.items: list[EvidenceItem] = self._load()

    def _load(self) -> list[EvidenceItem]:
        if not self.index_path.is_file():
            return []
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        return [EvidenceItem.model_validate(i) for i in data.get("items", [])]

    def _save(self) -> None:
        atomic_write_json(
            self.index_path, {"items": [i.model_dump(mode="json") for i in self.items]}
        )

    def add(
        self,
        *,
        type: str,
        content: str,
        description: str = "",
        command: str = "",
        exit_code: Optional[int] = None,
    ) -> EvidenceItem:
        evidence_id = f"EVD-{len(self.items) + 1:03d}"
        artifact = self.store.evidence_dir / f"{evidence_id}.txt"
        write_immutable(artifact, content)
        item = EvidenceItem(
            id=evidence_id,
            type=type,
            command=command,
            exit_code=exit_code,
            artifact_path=str(artifact),
            sha256=sha256_text(content),
            description=description,
        )
        self.items.append(item)
        self._save()
        return item

    def summary_markdown(self) -> str:
        if not self.items:
            return "_No evidence recorded._"
        lines = []
        for i in self.items:
            exec_note = (
                f"command `{i.command}` exit {i.exit_code}" if i.command else "no command executed"
            )
            lines.append(
                f"- **{i.id}** [{i.type}] {i.description or Path(i.artifact_path).name} "
                f"({exec_note}, sha256 {i.sha256[:12]})"
            )
        return "\n".join(lines)
