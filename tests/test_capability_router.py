"""Capability Router tests against the REAL current-session harness snapshot."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capability_router import route
from harness_skill_snapshot import load_snapshot

FIX = Path(__file__).parent / "fixtures" / "harness-skill-snapshot.baseline.json"


def _snapshot_with_git_verified():
    data = json.loads(FIX.read_text(encoding="utf-8"))
    for entry in data["skills"]:
        if entry["identity"] == "git-state-change-regression":
            entry["verified_callable"] = True
            entry["permission"] = "granted"
    p = FIX.parent / "snapshot.git-verified.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return load_snapshot(p)


def test_git_wu_before_verification_selects_pending_real_invocation(tmp_path):
    """Selection precedes invocation; the selected candidate remains explicitly unverified."""
    data = json.loads(FIX.read_text(encoding="utf-8"))
    for entry in data["skills"]:
        if entry["identity"] == "git-state-change-regression":
            entry["permission"] = "granted"  # Host listed it as callable.
            entry["verified_callable"] = False
    pending_path = tmp_path / "snapshot.git-pending.json"
    pending_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    decision = route(load_snapshot(pending_path), "执行一次 Git 状态安全检查，确认改动范围与未提交变更")
    assert decision.decision == "git-state-change-regression"
    assert decision.ranked[0][0].verified_callable is False


def test_git_wu_after_real_verification_selects_git_skill():
    """After the session really loads git-state-change-regression, the Router auto-selects it."""
    snap = _snapshot_with_git_verified()
    decision = route(snap, "执行一次 Git 状态安全检查，确认改动范围与未提交变更")
    assert decision.decision == "git-state-change-regression"
    assert decision.reason.startswith("best text overlap")


def test_no_hardcoded_identity_selection():
    """Renaming the identity (same description, still verified) must not change selection."""
    data = json.loads(FIX.read_text(encoding="utf-8"))
    for entry in data["skills"]:
        if entry["identity"] == "git-state-change-regression":
            entry["identity"] = "renamed-not-in-catalog"
            entry["verified_callable"] = True
            entry["permission"] = "granted"
    p = FIX.parent / "snapshot.renamed.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    decision = route(load_snapshot(p), "执行一次 Git 状态安全检查")
    assert decision.decision == "renamed-not-in-catalog"


def test_irrelevant_wu_returns_no_eligible():
    snap = _snapshot_with_git_verified()
    decision = route(snap, "对木星卫星轨道做一次拉格朗日点力学推导")
    assert decision.decision == "NO_ELIGIBLE_HARNESS_SKILL"


def test_exclusion_matrix_records_machine_reasons():
    snap = _snapshot_with_git_verified()
    decision = route(snap, "执行一次 Git 状态安全检查")
    for exclusion in decision.exclusions:
        assert exclusion.reason in {
            "not_available_in_current_session",
            "permission_denied",
            "permission_unknown",
            "identity_incomplete",
            "task_mismatch_no_text_overlap",
        }
    # An unverified candidate is not silently trusted; it remains marked pending
    # verification in the Router decision until the real Skill invocation returns.
    assert any(not candidate.verified_callable for candidate, _ in decision.ranked) is False
