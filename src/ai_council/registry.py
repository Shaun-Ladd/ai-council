"""Findings registry: structured lifecycle for reviewer and Judge findings."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from .models import Finding, FindingSeverity, FindingStatus, NewFinding, utcnow_iso


class FindingLifecycleError(Exception):
    pass


class FindingsRegistry:
    def __init__(self, findings: Optional[list[Finding]] = None):
        self.findings: list[Finding] = findings or []

    # -- persistence ------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "FindingsRegistry":
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([Finding.model_validate(f) for f in data.get("findings", [])])

    def dump(self) -> dict:
        return {"findings": [f.model_dump(mode="json") for f in self.findings]}

    # -- lookup -----------------------------------------------------------
    def get(self, finding_id: str) -> Finding:
        for f in self.findings:
            if f.id == finding_id:
                return f
        raise KeyError(f"Unknown finding id: {finding_id}")

    def has(self, finding_id: str) -> bool:
        return any(f.id == finding_id for f in self.findings)

    def open_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.status in (FindingStatus.OPEN, FindingStatus.ACCEPTED)]

    def open_blocking(self) -> list[Finding]:
        return [f for f in self.open_findings() if f.severity == FindingSeverity.BLOCKING]

    def human_required(self) -> list[Finding]:
        return [f for f in self.findings if f.status == FindingStatus.HUMAN_REQUIRED]

    # -- mutation ---------------------------------------------------------
    def _next_id(self, source_role: str) -> str:
        prefix = {"reviewer": "RVW", "judge": "JDG"}.get(source_role, "FND")
        count = sum(1 for f in self.findings if f.id.startswith(prefix)) + 1
        return f"{prefix}-{count:03d}"

    def add_new(
        self,
        new_findings: Iterable[NewFinding],
        *,
        source_role: str,
        proposal_version: int,
        round_no: int,
        judge_cycle: int = 0,
    ) -> list[Finding]:
        added = []
        for nf in new_findings:
            finding = Finding(
                id=self._next_id(source_role),
                title=nf.title,
                detail=nf.detail,
                severity=nf.severity,
                status=FindingStatus.OPEN,
                source_role=source_role,
                cited_section=nf.cited_section,
                why_it_matters=nf.why_it_matters,
                acceptance_condition=nf.acceptance_condition,
                proposal_version=proposal_version,
                created_round=round_no,
                judge_cycle=judge_cycle,
                history=[f"{utcnow_iso()} opened by {source_role} (round {round_no})"],
            )
            self.findings.append(finding)
            added.append(finding)
        return added

    def resolve(self, finding_ids: Iterable[str], *, by_role: str, note: str = "") -> list[str]:
        """Mark findings resolved.

        Authority: humans and the judge may resolve anything; the reviewer may
        resolve reviewer and judge findings (the orchestrator additionally
        requires an architect FIXED response for judge findings); the
        architect may resolve nothing — its fixes are confirmed by others.
        """
        resolved = []
        for fid in finding_ids:
            if not self.has(fid):
                continue
            f = self.get(fid)
            if f.status in (FindingStatus.RESOLVED, FindingStatus.SUPERSEDED):
                continue
            allowed = by_role in ("human", "judge") or (
                by_role == "reviewer" and f.source_role in ("reviewer", "judge")
            )
            if not allowed:
                raise FindingLifecycleError(
                    f"{by_role} cannot resolve finding {fid} opened by {f.source_role}"
                )
            f.status = FindingStatus.RESOLVED
            f.resolution_note = note
            f.history.append(f"{utcnow_iso()} resolved by {by_role}: {note}".rstrip(": "))
            resolved.append(fid)
        return resolved

    def reopen(self, finding_ids: Iterable[str], *, by_role: str, note: str = "") -> list[str]:
        reopened = []
        for fid in finding_ids:
            if not self.has(fid):
                continue
            f = self.get(fid)
            if f.status == FindingStatus.OPEN:
                continue
            f.status = FindingStatus.OPEN
            f.history.append(f"{utcnow_iso()} reopened by {by_role}: {note}".rstrip(": "))
            reopened.append(fid)
        return reopened

    def supersede(self, finding_ids: Iterable[str], *, by_role: str, note: str = "") -> list[str]:
        """Close findings as SUPERSEDED. Only the Judge (arbitration) or a
        human may overrule findings this way."""
        if by_role not in ("judge", "human"):
            raise FindingLifecycleError(f"{by_role} cannot supersede findings")
        superseded = []
        for fid in finding_ids:
            if not self.has(fid):
                continue
            f = self.get(fid)
            if f.status == FindingStatus.SUPERSEDED:
                continue
            f.status = FindingStatus.SUPERSEDED
            f.resolution_note = note
            f.history.append(f"{utcnow_iso()} superseded by {by_role}: {note}".rstrip(": "))
            superseded.append(fid)
        return superseded

    def mark_wont_fix(self, finding_id: str, *, human_authorized: bool, note: str = "") -> None:
        f = self.get(finding_id)
        if f.severity == FindingSeverity.BLOCKING and not human_authorized:
            raise FindingLifecycleError(
                f"Blocking finding {finding_id} cannot be marked WONT_FIX without human authorization"
            )
        f.status = FindingStatus.WONT_FIX
        f.history.append(f"{utcnow_iso()} marked WONT_FIX: {note}".rstrip(": "))

    def mark_human_required(self, finding_id: str, note: str = "") -> None:
        f = self.get(finding_id)
        f.status = FindingStatus.HUMAN_REQUIRED
        f.history.append(f"{utcnow_iso()} escalated to human: {note}".rstrip(": "))

    # -- rendering --------------------------------------------------------
    def to_markdown(self, only_open: bool = False) -> str:
        findings = self.open_findings() if only_open else self.findings
        if not findings:
            return "_No findings._"
        lines = []
        for f in findings:
            lines.append(
                f"- **{f.id}** [{f.severity.value}/{f.status.value}] {f.title}"
                + (f" (cites: {f.cited_section})" if f.cited_section else "")
            )
            if f.detail:
                lines.append(f"  - {f.detail}")
            if f.why_it_matters:
                lines.append(f"  - Why it matters: {f.why_it_matters}")
            if f.acceptance_condition:
                lines.append(f"  - Acceptance condition: {f.acceptance_condition}")
        return "\n".join(lines)
