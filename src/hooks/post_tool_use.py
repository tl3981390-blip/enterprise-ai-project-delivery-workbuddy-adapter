#!/usr/bin/env python3
"""PostToolUse bridge entry (candidate): record real tool execution evidence.

Only an enabled project with an active controller session can persist a receipt, and a
receipt is created exclusively from the host-provided tool_response. Model-claimed
"PASS" wording is rejected before any receipt logic runs.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bridge_state as bs  # noqa: E402
from evidence import (  # noqa: E402
    receipt_from_post_tool_use,
    reject_claimed_pass,
    utc_now_iso,
)
from project_gate import locate_enabled_root  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    root = locate_enabled_root(payload, os.environ)
    if root is not None:
        try:
            ts = utc_now_iso()
            session_id = payload.get("session_id")
            if isinstance(session_id, str) and session_id.strip():
                state = bs.load_state(root)
                if state is not None and bs.has_active_session(state, session_id):
                    if reject_claimed_pass(payload):
                        bs.append_audit(root, {
                            "kind": "evidence_claim_rejected", "event": "PostToolUse",
                            "session_id": session_id,
                            "reason": "evidence claim embedded outside a real tool_response",
                        }, ts)
                        print(json.dumps({}))
                        return 0
                    receipt = receipt_from_post_tool_use(payload, ts)
                    if receipt is not None:
                        action = bs.add_receipt(state, session_id, receipt)
                        bs.save_state(root, state, ts)
                        bs.append_audit(root, {
                            "kind": "tool_receipt", "action": action,
                            "event": "PostToolUse", "session_id": session_id,
                            "tool_name": receipt["tool_name"],
                            "digest": receipt["digest"],
                        }, ts)
                    else:
                        bs.append_audit(root, {
                            "kind": "tool_ignored", "event": "PostToolUse",
                            "session_id": session_id,
                            "reason": "no real tool_response present",
                        }, ts)
        except Exception as exc:
            try:
                bs.append_audit(root, {"kind": "error", "event": "PostToolUse",
                                       "error": str(exc)}, utc_now_iso())
            except Exception:
                pass
    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
