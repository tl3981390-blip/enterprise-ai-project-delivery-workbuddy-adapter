"""Invocation scope cleanup tests: temp context must not leak after a Work Unit."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scope_control import ScopeControl


def test_scope_context_removed_and_audited(tmp_path):
    audit = tmp_path / "audit"
    control = ScopeControl(audit)
    scope = control.open_scope("s1", "wu-git", "git-state-change-regression")
    probe = scope.ctx_dir / "temp-ctx.txt"
    probe.write_text("transient", encoding="utf-8")
    assert scope.ctx_dir.exists()
    scope.close()
    assert not scope.ctx_dir.exists()
    log = (audit / "scope-audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(log) == 2
    assert '"event": "scope_opened"' in log[0]
    assert '"event": "scope_closed"' in log[1]
    assert '"context_dir_exists_after": false' in log[1]


def test_double_close_is_idempotent(tmp_path):
    audit = tmp_path / "audit"
    control = ScopeControl(audit)
    scope = control.open_scope("s1", "wu-x", "k")
    scope.close()
    scope.close()
    log = (audit / "scope-audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(log) == 2  # no duplicate close audit


def test_context_manager_cleans_on_exit(tmp_path):
    audit = tmp_path / "audit"
    control = ScopeControl(audit)
    with control.open_scope("s1", "wu-y", "k") as scope:
        (scope.ctx_dir / "x.txt").write_text("t", encoding="utf-8")
    assert not scope.ctx_dir.exists()
