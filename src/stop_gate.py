"""Stop / Evidence Gate (requirement D).

The gate is reachable only when:
  * the project root is explicitly enabled (exact opt-in contract), and
  * a valid, active controller session exists for the Stop hook's session_id.

Outcomes:
  * project not enabled / root unresolvable  -> inert allow (continue), zero side effects
  * enabled but no legal controller session   -> fail-closed block (never silently pass)
  * enabled + session, evidence insufficient  -> fail-closed block with a precise reason
  * enabled + session, evidence sufficient    -> allow completion

Blocking a Stop means returning continue:false; the engine then keeps the agent working
with the reason injected.  This adapter never claims that a full Human Authority
controller is connected.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import bridge_state as bs
from evidence import EvidencePolicy, evidence_snapshot, evidence_sufficient
from project_gate import locate_enabled_root

# Allow completion when there is no project opt-in and no state (inert passthrough).
STATUS_LAZY_DISABLED = "lazy_disabled"
STATUS_NO_ROOT = "no_project_root"
STATUS_NO_CONTROLLER_SESSION = "no_controller_session"
STATUS_EVIDENCE_BLOCKED = "evidence_blocked"
STATUS_EVIDENCE_SATISFIED = "evidence_satisfied"


@dataclass(frozen=True)
class GateDecision:
    should_continue: bool
    reason: Optional[str]
    status: str

    @property
    def blocked(self) -> bool:
        return not self.should_continue

    def to_hook_json(self) -> dict[str, Any]:
        """JSON for the Stop hook stdout. continue:false blocks completion."""
        if self.should_continue:
            return {"continue": True, "systemMessage": ""}
        return {"continue": False, "reason": self.reason or "completion blocked by evidence gate"}


def _session_id(payload: dict[str, Any]) -> str:
    value = payload.get("session_id")
    return value if isinstance(value, str) and value.strip() else ""


def evaluate_stop_for(project_root: Any,
                      payload: dict[str, Any],
                      policy: Optional[EvidencePolicy] = None,
                      ts: Optional[str] = None,
                      state_loader=None) -> GateDecision:
    """Evaluate the Stop gate against a resolved project root.

    state_loader: optional callable(root) -> state|None for testability; defaults to
    bridge_state.load_state.
    """
    from evidence import utc_now_iso
    ts = ts or utc_now_iso()
    policy = policy or EvidencePolicy()
    loader = state_loader if state_loader is not None else bs.load_state

    try:
        state = loader(project_root)
    except bs.BridgeStateError as exc:
        # State exists but is untrustworthy: never let a corrupted state pass the gate.
        return GateDecision(False, f"bridge state unreadable ({exc}); failing closed", "no_controller_session")

    if state is None:
        return GateDecision(False,
                            "no controller session: bridge state was never created "
                            "(SessionStart hook did not bind a session for this project)",
                            STATUS_NO_CONTROLLER_SESSION)

    session_id = _session_id(payload)
    if not session_id or not bs.has_active_session(state, session_id):
        return GateDecision(False,
                            f"no active controller session for session_id={session_id or '<none>'}; "
                            "completion cannot be authorized without a bound session",
                            STATUS_NO_CONTROLLER_SESSION)

    receipts = bs.session_receipts(state, session_id)
    if evidence_sufficient(receipts, policy):
        return GateDecision(True, None, STATUS_EVIDENCE_SATISFIED)

    snapshot = evidence_snapshot(receipts)
    required = policy.required_tools or ("any real PostToolUse receipt",)
    reason = (
        f"evidence gate blocked completion: {snapshot['receipt_count']} real receipt(s) "
        f"(required >= {policy.min_receipts} from {', '.join(required)}); "
        "run the required verifiable tool executions so PostToolUse can record real "
        "evidence, then ask to complete again"
    )
    return GateDecision(False, reason, STATUS_EVIDENCE_BLOCKED)


def evaluate_stop(payload: dict[str, Any],
                  env: Optional[dict[str, str]] = None,
                  policy: Optional[EvidencePolicy] = None,
                  ts: Optional[str] = None) -> GateDecision:
    """Resolve the enabled project root from host context, then run the gate.

    No resolvable enabled root => fully inert allow.  This is what keeps every
    non-opted-in project completely unaffected by the bridge.
    """
    root = locate_enabled_root(payload, env)
    if root is None:
        return GateDecision(True, None, STATUS_LAZY_DISABLED)
    return evaluate_stop_for(root, payload, policy=policy, ts=ts)
