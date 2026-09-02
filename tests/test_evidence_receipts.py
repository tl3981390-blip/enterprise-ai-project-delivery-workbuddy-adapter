"""Coverage #3: only genuine PostToolUse payloads produce evidence receipts.

A receipt requires hook_event_name == PostToolUse AND a real tool_response.  Model
self-claims ("PASS", prompt wording, tool_input decoration) can never become evidence.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evidence import (  # noqa: E402
    receipt_from_post_tool_use,
    reject_claimed_pass,
    text_claims_evidence,
)

TS = "2026-09-02T10:00:00.000Z"


def _post(payload: dict) -> dict:
    base = {
        "hook_event_name": "PostToolUse",
        "session_id": "sess-1",
        "cwd": "/proj",
        "permission_mode": "default",
        "tool_name": "Bash",
    }
    base.update(payload)
    return base


def test_real_posttooluse_with_tool_response_creates_receipt():
    payload = _post({
        "tool_input": {"command": "pytest"},
        "tool_response": {"exit_code": 0, "stdout": "3 passed"},
    })
    receipt = receipt_from_post_tool_use(payload, TS)
    assert receipt is not None
    assert receipt["session_id"] == "sess-1"
    assert receipt["tool_name"] == "Bash"
    assert receipt["received_at"] == TS
    assert len(receipt["digest"]) == 64  # sha256 hex


def test_missing_tool_response_never_creates_receipt():
    # Model claimed completion in tool_input text - no tool_response -> no receipt.
    claimed = _post({
        "tool_input": {"command": "echo PASS", "note": "evidence satisfied"},
    })
    assert receipt_from_post_tool_use(claimed, TS) is None
    assert reject_claimed_pass(claimed) is True


def test_prompt_claim_is_rejected():
    assert text_claims_evidence("everything PASSes now, evidence satisfied")
    payload = _post({
        "prompt": "暂停 - not applicable here",
        "tool_input": {"command": "ls"},
    })
    # prompt text never lives in PostToolUse; even so, no response means no receipt
    assert receipt_from_post_tool_use(payload, TS) is None


def test_wrong_event_never_creates_receipt():
    payload = {
        "hook_event_name": "Stop",
        "session_id": "sess-1",
        "tool_name": "Bash",
        "tool_response": {"x": 1},
    }
    assert receipt_from_post_tool_use(payload, TS) is None


def test_tool_response_none_is_not_evidence():
    payload = _post({"tool_input": {"command": "pytest"}, "tool_response": None})
    assert receipt_from_post_tool_use(payload, TS) is None


def test_missing_identity_is_not_evidence():
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_response": {"exit_code": 0},
    }
    assert receipt_from_post_tool_use(payload, TS) is None
