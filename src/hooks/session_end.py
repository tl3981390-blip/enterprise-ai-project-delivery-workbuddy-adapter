#!/usr/bin/env python3
"""SessionEnd bridge entry (candidate).

Closes the controller session episode for an explicitly enabled project. Inert for
everything else. SessionEnd reasons on this host: clear / logout /
prompt_input_exit / other (verified in the bundled engine source).
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
            state = bs.load_state(root)
            if state is not None:
                session_id = payload.get("session_id")
                if isinstance(session_id, str) and session_id.strip():
                    ts = utc_now_iso()
                    action = bs.end_session(state, session_id,
                                            str(payload.get("reason") or "other"), ts)
                    if action == "closed":
                        bs.save_state(root, state, ts)
                    bs.append_audit(root, {
                        "kind": "session_end", "action": action,
                        "session_id": session_id, "event": "SessionEnd",
                        "reason": payload.get("reason") or "other",
                    }, ts)
        except Exception as exc:
            try:
                bs.append_audit(root, {"kind": "error", "event": "SessionEnd",
                                       "error": str(exc)}, utc_now_iso())
            except Exception:
                pass
    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
