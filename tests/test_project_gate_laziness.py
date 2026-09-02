"""Coverage #1 and #2 (part): project gate exactness and full laziness (requirement A).

An un-enabled project must be completely inert: no state directory, no Controller
Session, no Stop interception, no side effects at all - even when hook-like payloads
arrive and even when a .workbuddy directory exists for other purposes.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from controller_contract import project_enabled  # noqa: E402
from project_gate import (  # noqa: E402
    enabled_at,
    locate_enabled_root,
    read_contract,
)
from stop_gate import evaluate_stop, STATUS_LAZY_DISABLED  # noqa: E402

GATE = {"adapter": "enterprise-ai-project-delivery-workbuddy-adapter", "enabled": True}


def _write_contract(root: Path, content) -> None:
    target = root / ".workbuddy" / "delivery-contract.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, dict):
        content = json.dumps(content)
    target.write_text(content, encoding="utf-8")


def _stop_payload(root: Path) -> dict:
    return {"hook_event_name": "Stop", "session_id": "sess-1", "cwd": str(root)}


def test_gate_is_exact():
    assert project_enabled(GATE)
    assert not project_enabled({**GATE, "extra": True})
    assert not project_enabled({**GATE, "enabled": False})
    assert not project_enabled({"adapter": "another-adapter", "enabled": True})


def test_contract_read_never_raises_on_missing_or_malformed(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    assert read_contract(root) is None
    assert enabled_at(root) is False
    _write_contract(root, "{ not json")
    assert read_contract(root) is None
    assert enabled_at(root) is False


def test_disabled_or_wrong_project_is_lazy_on_stop(tmp_path):
    for name, contract in [
        ("missing", None),
        ("disabled", {**GATE, "enabled": False}),
        ("wrong-adapter", {"adapter": "someone-else", "enabled": True}),
        ("extra-key", {**GATE, "ignored": 1}),
    ]:
        root = tmp_path / name
        root.mkdir()
        if contract is not None:
            _write_contract(root, contract)
        decision = evaluate_stop(_stop_payload(root), env={"CODEBUDDY_PROJECT_DIR": str(root)})
        assert decision.should_continue is True, name  # inert allow, no interception
        assert decision.status == STATUS_LAZY_DISABLED, name
        # No state dir, no Controller Session, nothing created anywhere.
        assert not (root / ".workbuddy" / "bridge").exists(), name
        assert (root / ".workbuddy").exists() == (contract is not None), name


def test_enabled_root_is_resolved_only_from_host_context(tmp_path):
    a = tmp_path / "proj-a"
    b = tmp_path / "proj-b"
    for root in (a, b):
        root.mkdir()
        _write_contract(root, GATE)
    env = {"CODEBUDDY_PROJECT_DIR": str(a)}
    payload_with_cwd_b = _stop_payload(b)
    # Environment (project dir) wins over payload cwd; the other root stays untouched.
    assert locate_enabled_root(payload_with_cwd_b, env=env) == a
    assert locate_enabled_root(_stop_payload(b), env={}) == b


def test_unresolvable_root_is_inert(tmp_path):
    decision = evaluate_stop(
        {"hook_event_name": "Stop", "session_id": "s"},
        env={"CODEBUDDY_PROJECT_DIR": str(tmp_path / "does-not-exist")},
    )
    assert decision.should_continue is True
    assert decision.status == STATUS_LAZY_DISABLED
