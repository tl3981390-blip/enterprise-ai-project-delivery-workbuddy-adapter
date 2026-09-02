#!/usr/bin/env python3
"""Inspect a local WorkBuddy installation without changing its configuration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from controller_contract import evaluate_hook_contract


KNOWN_HOOKS = {"SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
               "Notification", "Stop", "SubagentStop", "PreCompact"}


def probe(home: Path) -> dict:
    settings = home / "settings.json"
    plugins = home / "plugins"
    official_hookify = plugins / "marketplaces" / "codebuddy-plugins-official" / "plugins" / "hookify" / "hooks" / "hooks.json"
    # WorkBuddy's documented Hook surface gives session_id but not a trusted conversation/message pair.
    observed_payload_shape = {"session_id": "host-provided"}
    readiness = evaluate_hook_contract(observed_payload_shape, KNOWN_HOOKS)
    return {
        "adapter_version": "0.1.0-dev",
        "workbuddy_home": str(home),
        "read_only_probe": True,
        "settings_present": settings.is_file(),
        "plugins_present": plugins.is_dir(),
        "hookify_contract_present": official_hookify.is_file(),
        "observed_hook_events": sorted(KNOWN_HOOKS),
        "controller_status": readiness.status,
        "missing_authority_fields": list(readiness.missing_fields),
        "missing_user_control_events": list(readiness.missing_events),
        "notes": list(readiness.notes),
        "safe_subset": ["project-scoped persistence", "PostToolUse receipts", "Stop/Evidence gate", "event replay detection"],
        "forbidden_claims": ["USER_PAUSE_CONNECTED", "USER_RESUME_CONNECTED", "USER_CANCEL_CONNECTED", "USER_CORRECTION_CONNECTED"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbuddy-home", required=True, type=Path)
    print(json.dumps(probe(parser.parse_args().workbuddy_home), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
