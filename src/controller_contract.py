"""Fail-closed WorkBuddy host-contract evaluation.

This module is intentionally independent of the Delivery Core.  It only decides whether
the observed WorkBuddy Hook surface can truthfully be used for a full controller binding.
It contains no filesystem access: pure decision logic over payload dictionaries.

Verified against this machine's bundled engine (cli/dist/codebuddy.js):
  * the hook stdin payload exposes session_id / transcript_path / cwd / permission_mode /
    hook_event_name plus event-specific fields only;
  * there is NO event_id field and NO trusted conversation_id / message_id in hook input;
  * PostToolUse additionally carries the real tool_response; Stop supports continue:false.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ADAPTER_ID = "enterprise-ai-project-delivery-workbuddy-adapter"

# A Hook execution id is replay metadata only and can never be treated as a user message id.
REQUIRED_HUMAN_CONTROL_FIELDS = ("session_id", "conversation_id", "message_id")
REQUIRED_HUMAN_CONTROL_EVENTS = ("USER_PAUSE", "USER_RESUME", "USER_CANCEL", "USER_CORRECTION")

# Human-controlled delivery transitions that must remain fail-closed until the host proves
# independent, trusted events carrying session_id + conversation_id + message_id.
HUMAN_CONTROL_TRANSITIONS = (
    "USER_PAUSE",
    "USER_RESUME",
    "USER_CANCEL",
    "USER_CORRECTION",
    "PLAN_APPROVAL",
    "REQUIREMENT_CHANGE",
)


@dataclass(frozen=True)
class ControllerReadiness:
    status: str
    missing_fields: tuple[str, ...]
    missing_events: tuple[str, ...]
    notes: tuple[str, ...]


def evaluate_hook_contract(payload: dict[str, Any], supported_events: set[str]) -> ControllerReadiness:
    """Return CONNECTED only for host-provided, verifiable authority primitives.

    A user prompt string, Hook execution id, or model classification can never fill an
    authority field.  `event_id` is intentionally excluded from REQUIRED_HUMAN_CONTROL_FIELDS.
    """
    missing_fields = tuple(field for field in REQUIRED_HUMAN_CONTROL_FIELDS
                           if not isinstance(payload.get(field), str) or not payload[field].strip())
    missing_events = tuple(event for event in REQUIRED_HUMAN_CONTROL_EVENTS if event not in supported_events)
    if not missing_fields and not missing_events:
        return ControllerReadiness("CONTROLLER_CONNECTED", (), (),
                                   ("host exposes trusted user-control primitives",))
    notes = ["full Human Authority bridge remains fail-closed"]
    if "message_id" in missing_fields:
        notes.append("Hook event_id is replay metadata only, not a user message identity")
    return ControllerReadiness("CONTROLLER_NOT_CONNECTED", missing_fields, missing_events, tuple(notes))


def project_enabled(contract: dict[str, Any]) -> bool:
    """Candidate hooks are inert unless the project owner has explicitly opted in.

    The gate is exact: a single extra or missing key disables the bridge.  This mirrors the
    verified local expectation that nothing is enabled until the owner writes this exact file.
    """
    return contract == {"adapter": ADAPTER_ID, "enabled": True}
