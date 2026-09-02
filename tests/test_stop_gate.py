"""Coverage #4 and #5: Stop / Evidence Gate behavior (requirement D).

* No evidence at all           -> completion intercepted (blocked)
* Evidence below the policy    -> completion still intercepted
* Evidence at/above the policy -> completion allowed
* Project disabled / no root   -> fully inert allow (nothing to do with the gate)
* Enabled but no legal session -> fail-closed block (a gate without a session can never
                                  authorize completion)
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import bridge_state as bs  # noqa: E402
from evidence import (  # noqa: E402
    EvidencePolicy,
    receipt_from_post_tool_use,
)
from stop_gate import (  # noqa: E402
    STATUS_EVIDENCE_BLOCKED,
    STATUS_EVIDENCE_SATISFIED,
    STATUS_LAZY_DISABLED,
    STATUS_NO_CONTROLLER_SESSION,
    evaluate_stop,
    evaluate_stop_for,
)

TS = "2026-09-02T10:00:00.000Z"
GATE = {"adapter": "enterprise-ai-project-delivery-workbuddy-adapter", "enabled": True}


def _enable(root: Path) -> None:
    target = root / ".workbuddy" / "delivery-contract.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(GATE), encoding="utf-8")


def _stop_payload(root: Path, session: str = "sess-1") -> dict:
    return {"hook_event_name": "Stop", "session_id": session, "cwd": str(root)}


def _tool_payload(root: Path, session: str = "sess-1", command: str = "pytest -q") -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": session,
        "cwd": str(root),
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"exit_code": 0, "stdout": "3 passed"},
    }


def _active_session_state(root: Path) -> dict:
    state = bs.empty_state(root, TS)
    bs.bind_session(state, "sess-1", "startup", "", TS)
    bs.save_state(root, state, TS)
    return state


def test_stop_with_no_evidence_is_intercepted(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _enable(root)
    _active_session_state(root)
    decision = evaluate_stop(_stop_payload(root), env={"CODEBUDDY_PROJECT_DIR": str(root)})
    assert decision.blocked
    assert decision.status == STATUS_EVIDENCE_BLOCKED
    assert decision.to_hook_json()["continue"] is False
    assert "evidence" in (decision.reason or "").lower()


def test_stop_with_insufficient_evidence_is_still_intercepted(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _enable(root)
    state = _active_session_state(root)
    # one real receipt, policy requires two
    receipt = receipt_from_post_tool_use(_tool_payload(root), TS)
    assert bs.add_receipt(state, "sess-1", receipt) == "recorded"
    bs.save_state(root, state, TS)

    policy = EvidencePolicy(min_receipts=2)
    decision = evaluate_stop(_stop_payload(root),
                             env={"CODEBUDDY_PROJECT_DIR": str(root)}, policy=policy)
    assert decision.blocked
    assert decision.status == STATUS_EVIDENCE_BLOCKED
    assert "1" in (decision.reason or "")  # snapshot says how many receipts exist


def test_stop_with_sufficient_evidence_is_allowed(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _enable(root)
    state = _active_session_state(root)
    receipt = receipt_from_post_tool_use(_tool_payload(root), TS)
    assert bs.add_receipt(state, "sess-1", receipt) == "recorded"
    bs.save_state(root, state, TS)

    decision = evaluate_stop(_stop_payload(root), env={"CODEBUDDY_PROJECT_DIR": str(root)})
    assert decision.should_continue
    assert decision.status == STATUS_EVIDENCE_SATISFIED


def test_stop_requires_a_legal_controller_session(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _enable(root)
    # Enabled project, but SessionStart never bound a session.
    decision = evaluate_stop(_stop_payload(root), env={"CODEBUDDY_PROJECT_DIR": str(root)})
    assert decision.blocked
    assert decision.status == STATUS_NO_CONTROLLER_SESSION

    # A different session id than the bound one is not a legal session either.
    _active_session_state(root)
    decision = evaluate_stop(_stop_payload(root, session="other-session"),
                             env={"CODEBUDDY_PROJECT_DIR": str(root)})
    assert decision.blocked
    assert decision.status == STATUS_NO_CONTROLLER_SESSION


def test_disabled_project_stop_is_inert_allow(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    target = root / ".workbuddy" / "delivery-contract.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({**GATE, "enabled": False}), encoding="utf-8")
    decision = evaluate_stop(_stop_payload(root), env={"CODEBUDDY_PROJECT_DIR": str(root)})
    assert decision.should_continue
    assert decision.status == STATUS_LAZY_DISABLED


def test_corrupt_state_blocks_fail_closed(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _enable(root)
    bridge = root / ".workbuddy" / "bridge"
    bridge.mkdir(parents=True)
    (bridge / "STATE.json").write_text("{ broken json", encoding="utf-8")
    decision = evaluate_stop_for(root, _stop_payload(root))
    assert decision.blocked
    assert decision.status == STATUS_NO_CONTROLLER_SESSION
