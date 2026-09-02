#!/usr/bin/env python3
"""UserPromptSubmit passthrough (documentation only - NOT registered by default).

The verified host hook payload for UserPromptSubmit carries only the prompt text plus
the common fields. There is no trusted conversation_id / message_id and no dedicated
pause/resume/cancel/correction event, so the text in a prompt can never authorize a
runtime state change. This entry exists to make that fail-closed behavior explicit:
it always exits 0 with an empty payload and never mutates bridge state.
"""
from __future__ import annotations

import json
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    # human_authority.user_text_is_authority() is a constant False; nothing here ever
    # transitions runtime state based on prompt wording.
    _ = payload
    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
