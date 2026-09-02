"""Tool evidence (requirement C): only real PostToolUse receipts.

A receipt exists only when the host PostToolUse hook input carries an actual
`tool_response` produced by a completed tool execution.  A model's self-asserted
"PASS" text, a claim embedded in tool_input, a user prompt, or any payload that lacks
the real tool_response field can never become evidence.

The verified engine on this machine constructs the PostToolUse input as:

    {..., hook_event_name: "PostToolUse", tool_name, tool_input, tool_response}

so the presence of tool_response is exactly the real-execution signal we can trust.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from bridge_state import canonical_signature


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _safe_str(value: Any) -> str:
    return value if isinstance(value, str) and value.strip() else ""


def _receipt_signature(payload: dict[str, Any]) -> str:
    """Signature of the *real* tool execution facts the host reported."""
    return canonical_signature({
        "hook_event_name": payload.get("hook_event_name"),
        "session_id": payload.get("session_id"),
        "tool_name": payload.get("tool_name"),
        "tool_input": payload.get("tool_input"),
        "tool_response": payload.get("tool_response"),
        "cwd": payload.get("cwd"),
    })


def receipt_from_post_tool_use(payload: dict[str, Any],
                               ts: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Build a receipt only from a genuine PostToolUse payload with a real tool_response.

    Returns None for anything else - fabricated claims can never be a receipt here.
    """
    if payload.get("hook_event_name") != "PostToolUse":
        return None
    session_id = _safe_str(payload.get("session_id"))
    tool_name = _safe_str(payload.get("tool_name"))
    if not session_id or not tool_name:
        return None
    if "tool_response" not in payload or payload.get("tool_response") is None:
        # The tool did execute but produced no response, or the payload is not genuine.
        return None
    return {
        "session_id": session_id,
        "tool_name": tool_name,
        "digest": _receipt_signature(payload),
        "received_at": ts or utc_now_iso(),
    }


# ---------------------------------------------------------------------------
# Fabrication guardrails
# ---------------------------------------------------------------------------

EVIDENCE_CLAIM_MARKERS = (
    "PASS",
    "evidence satisfied",
    "evidence_satisfied",
    "delivery evidence",
    "all evidence collected",
)


def text_claims_evidence(text: str) -> bool:
    """True when a text claims evidence/pass. Such text never creates a receipt."""
    upper = (text or "").upper()
    return any(marker.upper() in upper for marker in EVIDENCE_CLAIM_MARKERS)


def reject_claimed_pass(payload: dict[str, Any]) -> bool:
    """Guard: any evidence claim living outside a real tool_response is rejected.

    Returns True when the payload should be ignored for evidence purposes even if the
    model decorated tool_input or a prompt with PASS-style wording.
    """
    claimed = text_claims_evidence(str(payload.get("prompt") or ""))
    tool_input = payload.get("tool_input") or {}
    if isinstance(tool_input, dict):
        for key, value in tool_input.items():
            if isinstance(value, str) and text_claims_evidence(value):
                claimed = True
    return claimed


# ---------------------------------------------------------------------------
# Evidence policy and gate input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidencePolicy:
    """Minimal adapter-side evidence requirement.

    The bridge never imports the Delivery Core's evidence model.  This policy is a
    bridge-local, configurable threshold; the default stays deliberately strict about
    *verifiability* rather than about any Core-specific criteria.
    """
    min_receipts: int = 1
    required_tools: tuple[str, ...] = ()  # empty = any real tool with a response counts
    replay_window_seconds: Optional[int] = None

    def with_min(self, minimum: int) -> "EvidencePolicy":
        return EvidencePolicy(min_receipts=minimum, required_tools=self.required_tools,
                              replay_window_seconds=self.replay_window_seconds)

    def with_required_tools(self, tools: tuple[str, ...]) -> "EvidencePolicy":
        return EvidencePolicy(min_receipts=self.min_receipts, required_tools=tools,
                              replay_window_seconds=self.replay_window_seconds)


def evidence_snapshot(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    distinct = sorted({r.get("tool_name", "?") for r in receipts})
    return {
        "receipt_count": len(receipts),
        "distinct_tools": distinct,
        "tools_present": sorted({r.get("tool_name", "?") for r in receipts}),
        "first_receipt_at": receipts[0].get("received_at") if receipts else None,
        "last_receipt_at": receipts[-1].get("received_at") if receipts else None,
    }


def evidence_sufficient(receipts: list[dict[str, Any]], policy: EvidencePolicy) -> bool:
    if not receipts:
        return False
    if len(receipts) < policy.min_receipts:
        return False
    if policy.required_tools:
        present = {r.get("tool_name") for r in receipts}
        if not set(policy.required_tools).issubset(present):
            return False
    return True
