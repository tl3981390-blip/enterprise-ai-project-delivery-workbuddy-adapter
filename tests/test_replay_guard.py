"""Coverage #6: repeated / replayed Hook events are rejected.

The verified host hook input carries NO event_id, so replay protection is a bounded,
session-scoped digest window plus an exact duplicate guard on stored receipts.  A
replayed tool event must never double-count evidence.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import bridge_state as bs  # noqa: E402
from evidence import receipt_from_post_tool_use  # noqa: E402

TS = "2026-09-02T10:00:00.000Z"
TS_LATER = "2026-09-02T10:01:00.000Z"  # > 30s window


def _tool_payload() -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": "sess-1",
        "cwd": "/proj",
        "tool_name": "Bash",
        "tool_input": {"command": "pytest -q"},
        "tool_response": {"exit_code": 0, "stdout": "3 passed"},
    }


def test_duplicate_tool_event_is_rejected_and_not_double_counted(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    state = bs.empty_state(root, TS)
    bs.bind_session(state, "sess-1", "startup", "", TS)

    receipt = receipt_from_post_tool_use(_tool_payload(), TS)
    assert receipt is not None
    assert bs.add_receipt(state, "sess-1", receipt) == "recorded"
    # Identical re-delivery of the same real tool event:
    assert bs.add_receipt(state, "sess-1", receipt) == "duplicate"

    receipts = bs.session_receipts(state, "sess-1")
    assert len(receipts) == 1  # never double counted


def test_bounded_replay_window_rejects_then_rearms(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    state = bs.empty_state(root, TS)
    sig = "some-host-payload-signature"
    assert bs.is_replay(state, sig, "sess-1", TS) is False   # first sighting
    assert bs.is_replay(state, sig, "sess-1", TS) is True    # within window -> replay
    assert bs.is_replay(state, sig, "sess-1", TS_LATER) is False  # window expired -> rearmed


def test_replay_scope_is_per_session(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    state = bs.empty_state(root, TS)
    sig = "same-payload-across-sessions"
    assert bs.is_replay(state, sig, "sess-a", TS) is False
    # Identical signature in a different session is NOT a replay (legit parallel work).
    assert bs.is_replay(state, sig, "sess-b", TS) is False


def test_duplicate_session_bind_does_not_multiply_episodes(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    state = bs.empty_state(root, TS)
    assert bs.bind_session(state, "sess-1", "startup", "", TS) == "created"
    assert bs.bind_session(state, "sess-1", "startup", "", TS) == "resumed"
    assert bs.bind_session(state, "sess-1", "startup", "", TS) == "resumed"
    assert len(state["sessions"]) == 1
    assert state["sessions"]["sess-1"]["episode"] == 1
