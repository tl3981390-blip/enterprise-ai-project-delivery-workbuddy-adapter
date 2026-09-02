#!/usr/bin/env python3
"""SessionStart bridge entry (candidate).

Inert unless the project root is explicitly enabled. When enabled it binds or resumes
the controller session and persists project-scoped bridge state. It never registers
anything, never touches WorkBuddy settings, and exits 0 with empty JSON on stdout so
ordinary conversations are unaffected.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bridge_state as bs  # noqa: E402
from evidence import utc_now_iso  # noqa: E402
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
            state = bs.load_state(root)
            if state is None:
                state = bs.empty_state(root, ts)
            session_id = payload.get("session_id")
            if isinstance(session_id, str) and session_id.strip():
                ts = utc_now_iso()
                action = bs.bind_session(
                    state,
                    session_id,
                    str(payload.get("source") or "startup"),
                    str(payload.get("transcript_path") or ""),
                    ts,
                )
                bs.save_state(root, state, ts)
                bs.append_audit(root, {
                    "kind": "session_bind", "action": action,
                    "session_id": session_id, "event": "SessionStart",
                    "source": payload.get("source") or "startup",
                }, ts)
        except Exception as exc:  # never break the host conversation
            try:
                bs.append_audit(root, {"kind": "error", "event": "SessionStart",
                                       "error": str(exc)}, utc_now_iso())
            except Exception:
                pass
    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
