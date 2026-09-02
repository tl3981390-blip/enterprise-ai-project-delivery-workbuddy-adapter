#!/usr/bin/env python3
"""Run the REAL Capability Router over a REAL current-session snapshot file.

usage: python tools/router_cli.py <snapshot.json> "<work unit text>" <out.json>

This is only a thin argv wrapper around the same modules the product uses; the
candidate source is the snapshot the session model wrote from its real
available_skills.  It performs no discovery of its own.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capability_router import route  # noqa: E402
from harness_skill_snapshot import load_snapshot  # noqa: E402


def main(argv: list[str]) -> int:
    snapshot_path, work_unit, out_path = argv[1], argv[2], argv[3]
    snapshot = load_snapshot(snapshot_path)
    decision = route(snapshot, work_unit)
    Path(out_path).write_text(json.dumps(decision.as_json(), ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(decision.decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
