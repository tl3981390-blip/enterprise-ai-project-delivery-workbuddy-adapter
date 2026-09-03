"""Bridge-owned skill discovery: Host receipts, never model-authored snapshots."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks" / "bridge"))

import bridge  # noqa: E402


def _payload(response):
    return {
        "session_id": "host-session-1",
        "hook_event_name": "PostToolUse",
        "tool_name": "Skill",
        "tool_use_id": "tool-real-1",
        "tool_input": {"skill": "skills"},
        "tool_response": response,
    }


def test_receipt_without_list_fails_closed_and_never_writes_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured, reason = bridge._capture_host_skill_list(
        _payload("Built-in command executed: /skills"))
    assert captured is False
    assert reason == "host_receipt_has_no_available_skills"
    assert not (tmp_path / ".codebuddy" / "bridge" / "artifacts" /
                "available-skills-snapshot.json").exists()


def test_host_attested_skill_list_writes_bridge_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured, path = bridge._capture_host_skill_list(_payload({"available_skills": [
        {"identity": "pdf", "description": "Read and inspect PDF documents.",
         "available": True, "permission": "granted", "verified_callable": False},
    ]}))
    assert captured is True
    snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    assert snapshot["source"] == "harness_available_skills"
    assert snapshot["provenance"]["hook_event_name"] == "PostToolUse"
    assert snapshot["provenance"]["tool_use_id"] == "tool-real-1"
    assert snapshot["skills"][0]["identity"] == "pdf"
