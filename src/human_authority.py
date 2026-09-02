"""Human Authority (requirement E) - permanently fail-closed on this host.

WorkBuddy's verified Hook surface does NOT supply trusted per-message user identity
(session_id + conversation_id + message_id) for human-controlled transitions, and it
has no distinct host events for USER_PAUSE / USER_RESUME / USER_CANCEL /
USER_CORRECTION / plan approval / requirement change.

Until that changes, EVERY such transition is rejected here:
  * evaluate_hook_contract() decides the rejection and lists exactly what is missing;
  * event_id (which does not even exist in the verified host input) would in any case
    be replay metadata only and never a user message identity;
  * natural-language words such as "pause"/"cancel"/"暂停"/"取消" can never change any
    runtime state (user_text_is_authority() is a constant False and there is no code
    path from prompt text to a state mutation).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from controller_contract import (
    HUMAN_CONTROL_TRANSITIONS,
    ControllerReadiness,
    evaluate_hook_contract,
)

NON_AUTHORITY_TEXT_MARKERS = (
    "暂停", "取消", "pause", "resume", "cancel", "继续", "stop", "停止",
    "approve", "批准", "requirement change", "变更需求",
)


@dataclass(frozen=True)
class AuthorityDecision:
    allowed: bool
    reason: str
    readiness: ControllerReadiness

    @property
    def fail_closed(self) -> bool:
        return not self.allowed


def evaluate_human_transition(event_name: str,
                              payload: dict[str, Any],
                              host_supported_events: set[str] | None = None) -> AuthorityDecision:
    """Decide a user-controlled delivery transition.

    Always fail-closed unless the host itself proves a trusted conversation/message
    identity AND distinct user-control events.  On this machine host_supported_events
    is empty, so every transition is rejected.
    """
    supported = set() if host_supported_events is None else set(host_supported_events)
    readiness = evaluate_hook_contract(payload, supported)
    missing: list[str] = []
    if event_name not in supported:
        # Even a fully 'connected' readiness must not authorize a transition whose own
        # dedicated host event was never observed.
        missing.append(f"missing host events: {event_name}")
    if readiness.missing_fields:
        missing.append("missing host fields: " + ", ".join(readiness.missing_fields))
    if readiness.missing_events:
        missing.append("missing host events: " + ", ".join(readiness.missing_events))
    if not missing:
        return AuthorityDecision(True, "host-verified user control", readiness)
    reason = "FAIL_CLOSED: " + "; ".join(missing)
    return AuthorityDecision(False, reason, readiness)


def transition_allowed_only_with_host_identity(event_name: str,
                                               payload: dict[str, Any]) -> bool:
    """Convenience predicate used by every transition site."""
    if event_name not in HUMAN_CONTROL_TRANSITIONS:
        return False
    return evaluate_human_transition(event_name, payload).allowed


def user_text_is_authority(text: str) -> bool:
    """Natural-language 'authority' is never authority. Constant False by design."""
    return False


def matches_control_wording(text: str) -> bool:
    """Recognize control-sounding wording, only so we can prove it changes nothing."""
    upper = (text or "").lower()
    return any(marker.lower() in upper for marker in NON_AUTHORITY_TEXT_MARKERS)
