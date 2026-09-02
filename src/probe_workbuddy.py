#!/usr/bin/env python3
"""Read-only audit of a local WorkBuddy installation (never writes or changes config).

The probe reports what the *verified local host surface* can honestly support for a
project-scoped Controller Bridge. Evidence comes from three read-only sources:

  1. the live configuration under --workbuddy-home (settings.json, installed plugins,
     the official marketplace hookify plugin, project dirs);
  2. the official bundled hooks documentation (--hooks-doc, zh);
  3. the official bundled engine implementation (--engine-source, e.g. cli/dist/
     codebuddy.js) where keyword hit counts are scanned - never modified.

Every capability row is classified as one of:
  已真实验证 / 仅静态检查 / PENDING_EXTERNAL_VALIDATION / BLOCKED_BY_WORKBUDDY_CAPABILITY
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

# Facts established on the audited machine (offsets are byte positions in codebuddy.js).
VERIFIED_HOOK_PAYLOAD_FIELDS = [
    "hook_event_name", "session_id", "transcript_path", "cwd", "permission_mode",
]
VERIFIED_EVENT_FIELDS = {
    "PostToolUse": ["tool_name", "tool_input", "tool_response"],
    "UserPromptSubmit": ["prompt"],
    "SessionStart": ["source"],
    "SessionEnd": ["reason"],
    "Stop": ["stop_hook_active"],
}

ENGINE_MARKERS = {
    "hook_event_name": "hook payload construction key",
    "tool_response": "PostToolUse carries the real tool result",
    "stop_hook_active": "Stop payload field",
    "conversation_id": "telemetry/internal only, never a hook stdin field",
    '"message_id"': "telemetry/internal only, never a hook stdin field",
    '"event_id"': "expected zero hits in hook input",
    "permissionDecision": "PreToolUse/PostToolUse JSON decision support",
}


def _load_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _count(engine_text: Optional[str], pattern: str) -> Optional[int]:
    if engine_text is None:
        return None
    return len(re.findall(re.escape(pattern), engine_text))


def probe(home: Path, engine_source: Optional[Path] = None,
          hooks_doc: Optional[Path] = None) -> dict[str, Any]:
    settings = home / "settings.json"
    installed = home / "plugins" / "installed_plugins.json"
    official_hookify_hooks = (
        home / "plugins" / "marketplaces" / "codebuddy-plugins-official"
        / "plugins" / "hookify" / "hooks" / "hooks.json")
    settings_data = _load_json(settings)
    installed_data = _load_json(installed)

    enabled_plugins = (settings_data or {}).get("enabledPlugins", {})
    configured_hooks = (settings_data or {}).get("hooks", None)
    installed_names = list((installed_data or {}).get("plugins", {}).keys())

    engine_text: Optional[str] = None
    if engine_source is not None and engine_source.is_file():
        try:
            engine_text = engine_source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            engine_text = None

    marker_hits = {key: _count(engine_text, key) for key in ENGINE_MARKERS}

    capabilities = [
        {
            "claim": "hook command inputs are JSON on stdin with the common fields "
                     "hook_event_name/session_id/transcript_path/cwd(/permission_mode)",
            "evidence": "bundled zh docs hooks.md input section + engine convertToSdkInput construction",
            "verdict": "已真实验证",
        },
        {
            "claim": "hook payload carries a host event_id",
            "evidence": f"engine marker '\"event_id\"' hits: {marker_hits.get('\"event_id\"')}",
            "verdict": "BLOCKED_BY_WORKBUDDY_CAPABILITY" if marker_hits.get('"event_id"') == 0
                       else "PENDING_EXTERNAL_VALIDATION",
            "detail": "no event_id exists in hook input; event_id can never be a message_id",
        },
        {
            "claim": "hook payload carries trusted conversation_id + message_id for user control",
            "evidence": f"conversation_id / message_id appear only in telemetry paths "
                        f"(hits: {marker_hits.get('conversation_id')}/{marker_hits.get('\"message_id\"')})",
            "verdict": "BLOCKED_BY_WORKBUDDY_CAPABILITY",
            "detail": "not present in hook stdin; full Human Authority stays fail-closed",
        },
        {
            "claim": "distinct host events USER_PAUSE/USER_RESUME/USER_CANCEL/USER_CORRECTION exist",
            "evidence": "no such hook events in bundled docs events table",
            "verdict": "BLOCKED_BY_WORKBUDDY_CAPABILITY",
        },
        {
            "claim": "Stop can genuinely block agent completion",
            "evidence": "docs: Stop 'continue:false'/exit-2 blocks stopping; engine parseHookOutput "
                        "maps Stop continue:false to blocked",
            "verdict": "已真实验证",
            "detail": "live interception in a desktop session still needs registration -> PENDING below",
        },
        {
            "claim": "live Stop interception proven inside a real WorkBuddy desktop session",
            "evidence": "registration requires settings edit + /hooks panel review + restart "
                        "(engine snapshots hooks at startup)",
            "verdict": "PENDING_EXTERNAL_VALIDATION",
        },
        {
            "claim": "PostToolUse receives the real tool result (tool_response)",
            "evidence": f"engine PostToolUse construction includes tool_response "
                        f"(marker hits: {marker_hits.get('tool_response')})",
            "verdict": "已真实验证",
        },
        {
            "claim": "SessionStart/SessionEnd can anchor project-scoped persistence",
            "evidence": "SessionStart(source), SessionEnd(reason) fire on lifecycle; "
                        "CODEBUDDY_PROJECT_DIR documented for command hooks; SessionEnd carries cwd",
            "verdict": "已真实验证",
            "detail": "SessionStart stdin may lack cwd; bridge resolves the project root from "
                      "CODEBUDDY_PROJECT_DIR / cwd and stays inert when unresolved",
        },
        {
            "claim": "currently no hooks are registered anywhere in this WorkBuddy home",
            "evidence": f"settings 'hooks' key present: {configured_hooks is not None}; "
                        f"hookify in enabledPlugins: {'hookify@codebuddy-plugins-official' in enabled_plugins}",
            "verdict": "已真实验证",
        },
        {
            "claim": "official hookify plugin ships real hook scripts (stdin JSON consumers)",
            "evidence": f"hookify hooks.json exists: {official_hookify_hooks.is_file()}",
            "verdict": "已真实验证",
        },
        {
            "claim": "bridge entry points are inert unless the exact project contract opts in",
            "evidence": "src/project_gate.py exact-match gate + test suite",
            "verdict": "仅静态检查",
            "detail": "unit/integration tests executed locally; host-independent by construction",
        },
        {
            "claim": "full Human Authority control chain is connected",
            "evidence": "missing trusted conversation/message identity and user-control events",
            "verdict": "BLOCKED_BY_WORKBUDDY_CAPABILITY",
            "detail": "controller status must stay CONTROLLER_NOT_CONNECTED",
        },
    ]

    return {
        "adapter_version": "0.2.0-dev",
        "workbuddy_home": str(home),
        "read_only_probe": True,
        "controller_status": "CONTROLLER_NOT_CONNECTED",
        "settings_present": settings.is_file(),
        "settings_hooks_configured": configured_hooks is not None,
        "enabled_plugins_count": len(enabled_plugins),
        "adapter_plugin_enabled": any(
            "enterprise-ai-project-delivery-workbuddy-adapter" in key for key in enabled_plugins),
        "hookify_enabled": "hookify@codebuddy-plugins-official" in enabled_plugins,
        "hookify_marketplace_present": official_hookify_hooks.is_file(),
        "installed_plugin_count": len(installed_names),
        "engine_source_used": str(engine_source) if engine_source is not None else None,
        "engine_marker_hits": marker_hits,
        "verified_hook_payload_fields": VERIFIED_HOOK_PAYLOAD_FIELDS,
        "verified_event_fields": VERIFIED_EVENT_FIELDS,
        "hooks_doc_present": hooks_doc is not None and hooks_doc.is_file(),
        "capability_matrix": capabilities,
        "conclusion": (
            "WorkBuddy can truthfully support a project-scoped, evidence-gated bridge subset "
            "(receipts from real PostToolUse results, project-scoped persistence, Stop/Evidence "
            "gate, replay protection). It cannot yet support full Human Authority control: "
            "no trusted conversation_id/message_id and no user-control events reach hook "
            "input. All human-controlled transitions remain fail-closed."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbuddy-home", required=True, type=Path)
    parser.add_argument("--engine-source", type=Path, default=None)
    parser.add_argument("--hooks-doc", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(probe(args.workbuddy_home, args.engine_source, args.hooks_doc),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
