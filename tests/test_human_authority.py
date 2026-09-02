"""Coverage #7, #8, #9: Human Authority stays fail-closed (requirement E).

* #7 event_id can never substitute for a user message identity;
* #8 natural-language "pause"/"cancel" wording never changes runtime state;
* #9 every user-controlled transition is rejected while conversation_id/message_id
     (or the dedicated host events) are absent.
"""
from pathlib import Path
import copy
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import bridge_state as bs  # noqa: E402
from controller_contract import (  # noqa: E402
    HUMAN_CONTROL_TRANSITIONS,
    evaluate_hook_contract,
)
from evidence import receipt_from_post_tool_use  # noqa: E402
from human_authority import (  # noqa: E402
    AuthorityDecision,
    evaluate_human_transition,
    matches_control_wording,
    transition_allowed_only_with_host_identity,
    user_text_is_authority,
)

TS = "2026-09-02T10:00:00.000Z"


def test_event_id_cannot_replace_user_message_identity():
    readiness = evaluate_hook_contract({"session_id": "s", "event_id": "hook-123"}, set())
    assert readiness.status == "CONTROLLER_NOT_CONNECTED"
    assert "conversation_id" in readiness.missing_fields
    assert "message_id" in readiness.missing_fields

    decision = evaluate_human_transition("USER_PAUSE", {"session_id": "s", "event_id": "hook-123"})
    assert decision.fail_closed
    assert not transition_allowed_only_with_host_identity(
        "USER_PAUSE", {"session_id": "s", "event_id": "hook-123"})


def test_all_transitions_fail_closed_without_host_identity():
    for event in HUMAN_CONTROL_TRANSITIONS:
        decision = evaluate_human_transition(
            event, {"session_id": "s", "conversation_id": "c"})
        assert decision.fail_closed, event
        assert "FAIL_CLOSED" in decision.reason, event

        # conversation_id alone is still not enough: message_id is required too.
        decision = evaluate_human_transition(
            event, {"session_id": "s", "conversation_id": "c", "message_id": "m"})
        assert decision.fail_closed, event  # no dedicated host events on this host


def test_text_words_cannot_change_runtime_state(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    state = bs.empty_state(root, TS)
    bs.bind_session(state, "sess-1", "startup", "", TS)
    receipt = receipt_from_post_tool_use({
        "hook_event_name": "PostToolUse", "session_id": "sess-1",
        "cwd": str(root), "tool_name": "Bash",
        "tool_input": {"command": "pytest"}, "tool_response": {"exit_code": 0},
    }, TS)
    bs.add_receipt(state, "sess-1", receipt)
    bs.save_state(root, state, TS)
    before = json.dumps(bs.load_state(root), sort_keys=True)

    for wording in ("暂停", "取消", "pause the delivery", "cancel", "不要继续，取消"):
        assert user_text_is_authority(wording) is False
        assert matches_control_wording(wording) is True  # recognized but powerless
        # Even if a host event were attempted from this text, it stays fail-closed.
        decision = evaluate_human_transition("USER_PAUSE", {
            "session_id": "sess-1",
            "prompt": wording,
        })
        assert decision.fail_closed

    after = json.dumps(bs.load_state(root), sort_keys=True)
    assert after == before  # runtime state untouched: no pause, no cancel, no mutation


def test_human_transitions_never_touch_audit_or_sessions(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    audit_before = (root / ".workbuddy" / "bridge" / "AUDIT.jsonl").exists()
    for event in HUMAN_CONTROL_TRANSITIONS:
        evaluate_human_transition(event, {"session_id": "s"})
    assert (root / ".workbuddy" / "bridge" / "AUDIT.jsonl").exists() == audit_before
    assert not (root / ".workbuddy" / "bridge" / "STATE.json").exists()
