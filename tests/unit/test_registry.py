import pytest

from ai_council.models import FindingSeverity, FindingStatus, NewFinding
from ai_council.registry import FindingLifecycleError, FindingsRegistry


def _nf(title="Issue", severity=FindingSeverity.BLOCKING):
    return NewFinding(title=title, severity=severity, detail="d")


def test_ids_and_open_blocking():
    reg = FindingsRegistry()
    added = reg.add_new([_nf(), _nf(severity=FindingSeverity.MINOR)],
                        source_role="reviewer", proposal_version=1, round_no=1)
    assert [f.id for f in added] == ["RVW-001", "RVW-002"]
    judge = reg.add_new([_nf()], source_role="judge", proposal_version=1, round_no=1)
    assert judge[0].id == "JDG-001"
    assert {f.id for f in reg.open_blocking()} == {"RVW-001", "JDG-001"}


def test_resolution_authority():
    reg = FindingsRegistry()
    reg.add_new([_nf()], source_role="reviewer", proposal_version=1, round_no=1)
    reg.add_new([_nf()], source_role="judge", proposal_version=1, round_no=1)

    with pytest.raises(FindingLifecycleError):
        reg.resolve(["RVW-001"], by_role="architect")

    reg.resolve(["RVW-001"], by_role="reviewer")
    assert reg.get("RVW-001").status == FindingStatus.RESOLVED
    reg.resolve(["JDG-001"], by_role="judge")
    assert reg.get("JDG-001").status == FindingStatus.RESOLVED


def test_reopen():
    reg = FindingsRegistry()
    reg.add_new([_nf()], source_role="reviewer", proposal_version=1, round_no=1)
    reg.resolve(["RVW-001"], by_role="reviewer")
    reg.reopen(["RVW-001"], by_role="judge", note="not actually fixed")
    assert reg.get("RVW-001").status == FindingStatus.OPEN
    assert any("reopened" in h for h in reg.get("RVW-001").history)


def test_blocking_wont_fix_requires_human():
    reg = FindingsRegistry()
    reg.add_new([_nf()], source_role="reviewer", proposal_version=1, round_no=1)
    with pytest.raises(FindingLifecycleError):
        reg.mark_wont_fix("RVW-001", human_authorized=False)
    reg.mark_wont_fix("RVW-001", human_authorized=True, note="accepted risk")
    assert reg.get("RVW-001").status == FindingStatus.WONT_FIX


def test_non_blocking_wont_fix_allowed():
    reg = FindingsRegistry()
    reg.add_new([_nf(severity=FindingSeverity.ADVISORY)],
                source_role="reviewer", proposal_version=1, round_no=1)
    reg.mark_wont_fix("RVW-001", human_authorized=False)
    assert reg.get("RVW-001").status == FindingStatus.WONT_FIX


def test_persistence_roundtrip(tmp_path):
    reg = FindingsRegistry()
    reg.add_new([_nf()], source_role="reviewer", proposal_version=1, round_no=1)
    path = tmp_path / "findings.json"
    import json
    path.write_text(json.dumps(reg.dump()))
    loaded = FindingsRegistry.load(path)
    assert loaded.get("RVW-001").severity == FindingSeverity.BLOCKING


def test_supersede_authority_and_effect():
    reg = FindingsRegistry()
    reg.add_new([_nf()], source_role="reviewer", proposal_version=1, round_no=1)
    with pytest.raises(FindingLifecycleError):
        reg.supersede(["RVW-001"], by_role="reviewer")
    superseded = reg.supersede(["RVW-001", "NOPE-999"], by_role="judge", note="overruled")
    assert superseded == ["RVW-001"]
    assert reg.get("RVW-001").status == FindingStatus.SUPERSEDED
    assert reg.open_blocking() == []
