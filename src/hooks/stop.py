#!/usr/bin/env python3
"""Stop bridge entry (candidate): evidence gate at completion time.

Only an explicitly enabled project with a legal active controller session may invoke
the Evidence Gate. Without a session, or without sufficient real evidence, completion
is blocked (continue:false) and the reason is fed back to the agent. A non-enabled
project is fully inert: the script prints {"continue": true} and never creates state.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence import EvidencePolicy  # noqa: E402
from project_gate import locate_enabled_root  # noqa: E402
from stop_gate import evaluate_stop_for  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    root = locate_enabled_root(payload, os.environ)
    if root is None:
        # Fully inert for non-enabled projects: never block an ordinary conversation.
        print(json.dumps({"continue": True}))
        return 0
    try:
        decision = evaluate_stop_for(root, payload, policy=EvidencePolicy())
    except Exception as exc:  # fail closed, never crash the agent loop
        decision_reason = f"bridge error ({exc}); failing closed"
        print(json.dumps({"continue": False, "reason": decision_reason}))
        return 0
    print(json.dumps(decision.to_hook_json()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
