"""Fail-closed WorkBuddy host-contract evaluation.

This module is intentionally independent of the Delivery Core.  It only decides whether
the observed WorkBuddy Hook surface can truthfully be used for a full controller binding.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

REQUIRED_HUMAN_CONTROL_FIELDS = ("session_id", "conversation_id", "message_id")
REQUIRED_HUMAN_CONTROL_EVENTS = ("USER_PAUSE", "USER_RESUME", "USER_CANCEL", "USER_CORRECTION")


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
    """Candidate hooks are inert unless the project owner has explicitly opted in."""
    return contract == {"adapter": "enterprise-ai-project-delivery-workbuddy-adapter", "enabled": True}
