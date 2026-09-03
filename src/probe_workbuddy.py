#!/usr/bin/env python3
"""Read-only enterprise-demo preflight for a local WorkBuddy installation.

This tool deliberately separates three different claims.  A formally installed
Delivery Core is not proof that project hooks have fired in a fresh session;
neither is proof that WorkBuddy has exposed its current-session Skill list to
the Controller.  Keeping those claims separate makes a laptop preflight useful
instead of a source of false confidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

KNOWN_HOOKS = {"SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
               "Notification", "Stop", "SubagentStop", "PreCompact"}
REQUIRED_HOOKS = {"UserPromptSubmit", "PostToolUse", "Stop"}
CORE_NAME = "enterprise-ai-project-delivery"


def _core_candidates(home: Path) -> tuple[Path, ...]:
    """Return only conventional formal-install locations; do not scan disks."""
    return (
        home / "skills" / CORE_NAME,
        home.parent / ".workbuddy" / "skills" / CORE_NAME,
        home.parent / ".codebuddy" / "skills" / CORE_NAME,
    )


def _formal_core_status(home: Path) -> dict:
    for candidate in _core_candidates(home):
        info_path = candidate / "INSTALL_INFO.json"
        skill_path = candidate / "SKILL.md"
        if not info_path.is_file() or not skill_path.is_file():
            continue
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "status": "FAIL",
                "path": str(candidate),
                "reason": "FORMAL_ASSET_IDENTITY_MISSING_OR_INVALID",
            }
        identity = info.get("canonical_identity")
        if (info.get("skill_id") == CORE_NAME and isinstance(identity, str)
                and identity.startswith("tag v") and " -> commit " in identity):
            return {
                "status": "PASS",
                "path": str(candidate),
                "version": info.get("version"),
                "canonical_identity": identity,
            }
        return {
            "status": "FAIL",
            "path": str(candidate),
            "reason": "FORMAL_ASSET_IDENTITY_MISSING_OR_INVALID",
        }
    return {"status": "FAIL", "reason": "FORMAL_CORE_NOT_INSTALLED"}


def probe(home: Path) -> dict:
    settings = home / "settings.json"
    plugins = home / "plugins"
    official_hookify = plugins / "marketplaces" / "codebuddy-plugins-official" / "plugins" / "hookify" / "hooks" / "hooks.json"
    core = _formal_core_status(home)
    hook_prerequisites = REQUIRED_HOOKS.issubset(KNOWN_HOOKS)
    return {
        "adapter_version": "0.1.0-dev",
        "workbuddy_home": str(home),
        "read_only_probe": True,
        "settings_present": settings.is_file(),
        "plugins_present": plugins.is_dir(),
        "hookify_contract_present": official_hookify.is_file(),
        "observed_hook_events": sorted(KNOWN_HOOKS),
        "formal_core_installation": core,
        "project_scoped_controller": {
            "status": "PENDING_EXTERNAL_VALIDATION",
            "prerequisites_present": hook_prerequisites,
            "required_hook_events": sorted(REQUIRED_HOOKS),
            "reason": "a fresh WorkBuddy session must actually fire the project-scoped hooks",
        },
        "automatic_harness_skill_selection": {
            "status": "NOT_INCLUDED_BY_DESIGN",
            "reason": (
                "the documented /skills panel is UI-only and current PostToolUse "
                "receipts do not expose the current-session Skill identity/description list; "
                "this WorkBuddy delivery demonstration does not claim automatic selection"
            ),
            "forbidden_fallbacks": ["model-transcribed list", "local directory scan", "hardcoded candidate"],
        },
        "enterprise_demo_scope": {
            "status": "PASS" if core["status"] == "PASS" else "FAIL",
            "delivery_demo": "eligible after one fresh-session hook check" if core["status"] == "PASS" else "not eligible",
            "automatic_skill_selection_demo": "not eligible until host-attested discovery is available",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbuddy-home", required=True, type=Path)
    print(json.dumps(probe(parser.parse_args().workbuddy_home), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
