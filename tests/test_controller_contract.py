from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from controller_contract import evaluate_hook_contract, project_enabled


def test_event_id_cannot_replace_user_message_identity():
    result = evaluate_hook_contract({"session_id": "s", "event_id": "hook-event"}, set())
    assert result.status == "CONTROLLER_NOT_CONNECTED"
    assert "conversation_id" in result.missing_fields
    assert "message_id" in result.missing_fields


def test_full_control_requires_explicit_host_events_and_all_authority_fields():
    result = evaluate_hook_contract({"session_id": "s", "conversation_id": "c", "message_id": "m"}, {
        "USER_PAUSE", "USER_RESUME", "USER_CANCEL", "USER_CORRECTION"})
    assert result.status == "CONTROLLER_CONNECTED"


def test_project_gate_is_exact_and_default_denies():
    assert not project_enabled({})
    assert not project_enabled({"adapter": "enterprise-ai-project-delivery-workbuddy-adapter", "enabled": False})
    assert project_enabled({"adapter": "enterprise-ai-project-delivery-workbuddy-adapter", "enabled": True})
