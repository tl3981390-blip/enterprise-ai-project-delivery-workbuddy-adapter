#!/usr/bin/env python3
"""WorkBuddy host-event bridge entry points (Adapter branch, not the Core).

Invoked by the WorkBuddy host through project-scoped command hooks declared in
.codebuddy/settings.local.json (this project).  Each invocation receives the REAL
host event JSON on stdin and maps it into the formally installed Core runtime.

Commands (argv[1]):
  userpromptsubmit   -- REAL UserPromptSubmit -> capture verbatim ONLY (no intent guessing)
  declare-control    -- MODEL declares a control (PAUSE/RESUME/CANCEL/CORRECTION) on a
                        previously captured real message; the Core applies it
  posttooluse        -- REAL PostToolUse -> canonical evidence receipt
  stop               -- REAL Stop -> Core completion gate
  bootstrap          -- create the delivery session from the registered real goal

Division of labour: the bridge never interprets natural language.  Intent
recognition is the MODEL's job in the conversation; the bridge governs the model
by letting it declare controls ONLY on user messages the host actually captured
verbatim, and by keeping the declaration, rationale and original text in the
audit for human verification/correction.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import wbbridge as bridge

CONFIG = bridge.load_config()


def _signed_event(payload: dict, event_type: str, event_id: str) -> dict:
    from harness_adapter_core import sign_trusted_event  # noqa: PLC0415
    event = bridge.event_for(payload, event_type, event_id)
    return sign_trusted_event(event, transport_secret=CONFIG["transport_secret"])


def _controller(payload: dict):
    bridge.ensure_core_scripts(CONFIG)
    return bridge.make_controller(payload, CONFIG)


def _state_file(payload: dict) -> Path:
    return bridge.bridge_state_dir(payload) / "delivery" / f"{bridge.host_session_id(payload)}.json"


def _recent_pass_evidence(state: dict) -> list[str]:
    ledger = state.get("runtime", {}).get("evidence_ledger", [])
    return [e["evidence_id"] for e in ledger if e.get("status") == "PASS"][-5:]


def _git_checkpoint(session_id: str) -> dict:
    """Mechanical checkpoint identity read from the real working tree (no prose)."""
    def _run(cmd: list[str]) -> str:
        try:
            return subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=10, cwd=os.getcwd()).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    head = _run(["git", "rev-parse", "HEAD"])
    worktree = _run(["git", "rev-parse", "--show-toplevel"])
    return {"git_head": head or "unknown", "worktree_identity": worktree or str(Path.cwd()),
            "runtime_identity": session_id,
            "contract_hash": _run(["git", "status", "--porcelain"]),
            "evidence_anchor": "latest-pass-ledger"}


GOVERNANCE_NOTE = (
    "[delivery-control] The Adapter does NOT recognise colloquial intent; that is the "
    "MODEL's job. The message above was captured verbatim as adapter_message_id={mid}. "
    "If and only if YOU judge it to express a delivery control "
    "(PAUSE / RESUME / CANCEL / CORRECTION), declare it exactly once through the governed "
    "channel by piping a JSON object into: {cmd} declare-control . The JSON needs: "
    "\"session_id\", \"prompt\" (the verbatim text), \"kind\" (one of "
    "PAUSE/RESUME/CANCEL/CORRECTION), \"adapter_message_id\" (={mid}), \"rationale\", "
    "\"ambiguity_assessment\" (CLEAR or AMBIGUOUS), \"impacted_scope\", \"confidence\" "
    "(LOW/MEDIUM/HIGH), \"payload\" (required for CORRECTION) and "
    "\"hook_event_name\": \"UserPromptSubmit\". "
    "Fail-closed rules: CANCEL and CORRECTION ALWAYS open a Proposal and need a later real "
    "confirmation; an AMBIGUOUS reading also only opens a Proposal (state unchanged). Only a "
    "CLEAR PAUSE/RESUME applies directly. When a later real message confirms an open Proposal, "
    "add \"confirm_proposal_id\": <id returned by the previous declaration>. The Adapter rejects "
    "declarations not anchored to this real capture, forged ids, replay, other sessions, "
    "ambiguous self-confirmation, stale or cross-session messages."
)


def _declare_control_command() -> str:
    return f'"{sys.executable}" "{Path(__file__).resolve()}"'


def _maybe_bootstrap(payload: dict, sid: str, prompt: str, seq: int) -> None:
    """Create the delivery session from a REAL first user message.

    Only active when the project opts in with WBFDC_AUTO_BOOTSTRAP=1.  The user
    goal is the verbatim text the host actually delivered (seq 1), never text the
    Adapter invented.  The acceptance contract is a mechanical project input.
    """
    if os.environ.get("WBFDC_AUTO_BOOTSTRAP", "").strip().lower() not in {"1", "true"}:
        return
    if seq != 1 or _state_file(payload).is_file():
        return
    contract_raw = os.environ.get("WBFDC_CONTRACT", "[]")
    try:
        contract = json.loads(contract_raw)
    except ValueError:
        contract = []
    if not contract:
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    controller = _controller(payload)
    event = _signed_event(payload, "UserPromptSubmit", "bootstrap-goal-1")
    controller.start_session(event, original_user_request=prompt,
                             acceptance_contract=contract, auto_approve=True)
    _state_file(payload).parent.mkdir(parents=True, exist_ok=True)
    bridge.append_audit(payload, "bootstrap", {
        "decision": "session_started_from_real_first_user_prompt", "seq": seq})


def cmd_userpromptsubmit() -> dict:
    """Capture one REAL UserPromptSubmit verbatim.  Never interprets it.

    Intent recognition is the MODEL's job (in the conversation), so this hook
    does NOT guess a control kind and does NOT move the state machine.  It only
    records the real user message as an immutable origin.  When the model judges
    that the user is pausing/resuming/cancelling/correcting, it calls
    ``bridge.py declare-control`` pointing at this captured origin; the bridge
    re-checks that the message really was delivered by the host before it lets
    the Core apply anything.
    """
    payload = bridge.read_stdin_payload()
    event_name = payload.get("hook_event_name", "")
    prompt = str(payload.get("prompt") or "").strip()
    sid = bridge.host_session_id(payload)
    if event_name != "UserPromptSubmit":
        bridge.append_audit(payload, "userpromptsubmit", {"decision": "not_user_prompt_submit"})
        return {"continue": True}

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from human_authority import PromptStore, capture_user_prompt, NotUserOrigin  # noqa: PLC0415
    store = PromptStore(bridge.bridge_state_dir(payload) / "prompt-store.json")
    origin_payload = {"origin": "UserPromptSubmit", "session_id": sid, "prompt": prompt}
    try:
        origin = capture_user_prompt(origin_payload, store)
    except NotUserOrigin as exc:
        bridge.append_audit(payload, "userpromptsubmit", {"decision": "not_user_origin",
                                                          "error": str(exc)})
        return {"continue": True}
    except Exception as exc:  # noqa: BLE001
        bridge.append_audit(payload, "userpromptsubmit", {
            "decision": "capture_rejected", "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
        return {"continue": True}

    bridge.append_audit(payload, "userpromptsubmit", {
        "decision": "captured_verbatim",
        "adapter_message_id": origin.adapter_message_id,
        "kind": None,  # model interprets intent, never the hook
        "prompt_text": origin.prompt_text})
    # Any OPEN proposal that could no longer be confirmed by THIS new message is
    # dead (fail-closed: a proposal is only confirmable by the immediately
    # following real message; if the user says something else, it expires).
    from human_authority import ProposalStore  # noqa: PLC0415
    prop_store = ProposalStore(bridge.bridge_state_dir(payload) / "proposals.json")
    for proposal in prop_store.expire_on_capture(sid, origin.seq):
        bridge.append_audit(payload, "proposal", {
            "decision": "expired_by_newer_message",
            "proposal_id": proposal["proposal_id"], "kind": proposal["kind"],
            "source_seq": proposal["source_seq"], "captured_seq": origin.seq})
    _maybe_bootstrap(payload, sid, origin.prompt_text, origin.seq)
    return {
        "continue": True,
        "additionalContext": GOVERNANCE_NOTE.format(
            mid=origin.adapter_message_id, cmd=_declare_control_command()),
    }


def _apply_control(controller, payload: dict, kind: str, origin, revision: int,
                   state: dict, sid: str, rationale: str) -> None:
    """Ask the Core to apply one declared/confirmed control (never fabricates)."""
    reason = f"model interpretation of real user message {origin.adapter_message_id}"
    if rationale:
        reason += f": {rationale}"
    if kind == "PAUSE":
        controller.apply_user_pause(
            _signed_event(payload, "USER_PAUSE", origin.adapter_message_id),
            expected_contract_revision=revision,
            reason=reason,
            checkpoint_identity=_git_checkpoint(sid),
            evidence_ids=_recent_pass_evidence(state))
    elif kind == "RESUME":
        suspensions = state.get("runtime", {}).get("suspensions", [])
        suspension_id = suspensions[-1]["suspension_id"] if suspensions else None
        if not suspension_id:
            raise KeyError("user_suspension_not_found")
        controller.apply_user_resume(
            _signed_event(payload, "USER_RESUME", origin.adapter_message_id),
            expected_contract_revision=revision,
            suspension_id=suspension_id,
            current_identity=_git_checkpoint(sid),
            revalidation_evidence_ids=_recent_pass_evidence(state))
    elif kind == "CANCEL":
        controller.apply_user_cancel(
            _signed_event(payload, "USER_CANCEL", origin.adapter_message_id),
            expected_contract_revision=revision)
    elif kind == "CORRECTION":
        controller.apply_user_correction(
            _signed_event(payload, "USER_CORRECTION", origin.adapter_message_id),
            expected_contract_revision=revision,
            description=origin.payload or "user correction",
            violated_requirements=[origin.payload or "user correction"],
            root_cause_class="USER_REPORTED",
            related_checks=["user-stated requirement"])
    else:  # pragma: no cover - validated upstream
        raise ValueError(f"unsupported control kind: {kind}")


def cmd_declare_control() -> dict:
    """Model-side declaration of a control on a REAL captured user message.

    stdin payload (same event shape the hook delivered):
        {"session_id": ..., "prompt": "<verbatim user text the model is
        interpreting>", "kind": "PAUSE|RESUME|CANCEL|CORRECTION",
         "adapter_message_id": "<mid from the [delivery-control] note>",
         "payload": "<correction body, if kind=CORRECTION>",
         "rationale": "<short model note>",
         "ambiguity_assessment": "CLEAR|AMBIGUOUS",
         "impacted_scope": "...", "confidence": "LOW|MEDIUM|HIGH",
         "confirm_proposal_id": "<proposal id, when confirming>",
         "hook_event_name": "UserPromptSubmit"}

    Two-stage authority:
    * The message must exist in the prompt-store (a REAL UserPromptSubmit the host
      delivered verbatim), be undeclared, belong to the session that owns the
      newest capture, and carry the recomputed adapter_message_id.
    * CANCEL / CORRECTION / AMBIGUOUS declarations open a Proposal and never
      touch the Core.  Only CLEAR PAUSE/RESUME apply directly.
    * A confirmation must reference an OPEN proposal of the same session, be the
      real message immediately after the proposal's message, carry the same kind
      and a CLEAR assessment; then the Core applies the control once.
    """
    payload = bridge.read_stdin_payload()
    sid = bridge.host_session_id(payload)
    state_path = _state_file(payload)
    if not state_path.is_file():
        bridge.append_audit(payload, "declare", {"decision": "no_delivery_session"})
        return {"continue": True, "decision": "no_delivery_session"}

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from human_authority import (  # noqa: PLC0415
        AdapterUserOrigin, ControlRejected, PromptStore, ProposalRejected,
        ProposalStore, canonical_prompt_hash, is_confirm_gated,
        parse_control_declaration)
    store = PromptStore(bridge.bridge_state_dir(payload) / "prompt-store.json")
    proposals = ProposalStore(bridge.bridge_state_dir(payload) / "proposals.json")

    try:
        decl = parse_control_declaration(payload)
    except ControlRejected as exc:
        bridge.append_audit(payload, "declare",
                            {"decision": "declaration_invalid", "error": str(exc)})
        return {"continue": True, "decision": "declaration_invalid", "reason": str(exc)}
    p_hash = canonical_prompt_hash(decl.quoted_user_text)
    record = store.record(sid, p_hash)
    if record is None:
        bridge.append_audit(payload, "declare", {
            "decision": "no_matching_captured_message",
            "hint": "declaration must reference a REAL UserPromptSubmit captured verbatim",
            "adapter_message_id": decl.adapter_message_id,
            "prompt_hash": p_hash[:16]})
        return {"continue": True, "decision": "no_matching_captured_message"}

    # Authority follows the person actually talking now: only the session that
    # owns the newest captured message may declare (fail-closed under concurrency).
    newest = store.newest_capture()
    if newest is None or newest[0] != sid:
        bridge.append_audit(payload, "declare", {
            "decision": "cross_session_control_rejected",
            "declared_session": sid,
            "newest_session": newest[0] if newest else None,
            "hint": "the newest real user message belongs to another session"})
        return {"continue": True, "decision": "cross_session_control_rejected"}

    # Expiry: a control may only be declared on the NEWEST captured user message.
    latest_seq = store.latest_seq(sid)
    if int(record["seq"]) != latest_seq:
        bridge.append_audit(payload, "declare", {
            "decision": "declaration_expired", "kind": decl.kind,
            "declared_seq": record["seq"], "latest_seq": latest_seq,
            "hint": "a control may only be declared on the newest captured user message"})
        return {"continue": True, "decision": "declaration_expired"}

    # The adapter_message_id is derived from (session|seq|hash): a model that
    # pastes a real prompt but invents a different id is forging the anchor.
    expected_mid = ("am-" + _sha256_bytes(f"{sid}|{record['seq']}|{p_hash}".encode("utf-8"))[:32]
                    + f"-{record['seq']}")
    if decl.adapter_message_id != expected_mid:
        bridge.append_audit(payload, "declare", {
            "decision": "forged_adapter_message_id", "kind": decl.kind,
            "declared_mid": decl.adapter_message_id, "expected_mid": expected_mid,
            "seq": record["seq"]})
        return {"continue": True, "decision": "forged_adapter_message_id"}

    state = json.loads(state_path.read_text(encoding="utf-8"))
    revision = state.get("contract_revision", 1)
    open_proposal = proposals.open_proposal(sid)
    audit_common = {"kind": decl.kind, "adapter_message_id": expected_mid,
                    "seq": record["seq"], "rationale": decl.rationale,
                    "ambiguity_assessment": decl.ambiguity_assessment,
                    "impacted_scope": decl.impacted_scope, "confidence": decl.confidence}

    # ---- confirmation path (a DIFFERENT, later real message) -----------------
    if decl.confirm_proposal_id is not None:
        try:
            proposal = proposals.validate_confirmation(
                sid, decl.confirm_proposal_id, kind=decl.kind,
                ambiguity_assessment=decl.ambiguity_assessment,
                confirm_seq=int(record["seq"]))
        except ProposalRejected as exc:
            bridge.append_audit(payload, "declare", {
                "decision": "confirmation_rejected", "proposal_id": decl.confirm_proposal_id,
                "error": str(exc), **audit_common})
            return {"continue": True, "decision": "confirmation_rejected",
                    "reason": str(exc), "proposal_id": decl.confirm_proposal_id}
        if not store.declare(sid, p_hash, f"{decl.kind}:CONFIRM:{proposal['proposal_id']}"):
            bridge.append_audit(payload, "declare", {
                "decision": "confirmation_message_already_declared", **audit_common})
            return {"continue": True, "decision": "confirmation_message_already_declared"}
        confirmed = AdapterUserOrigin(
            adapter_message_id=expected_mid, session_id=sid, seq=record["seq"],
            prompt_hash=p_hash, prompt_text=record["text"], kind=decl.kind,
            payload=proposal.get("payload"), declared_by="MODEL_CONFIRMATION_OF_PROPOSAL",
            created_at="")
        controller = _controller(payload)
        try:
            _apply_control(controller, payload, proposal["kind"], confirmed,
                           revision, state, sid,
                           f"confirms proposal {proposal['proposal_id']} "
                           f"(proposed from {proposal['source_adapter_message_id']}): "
                           f"{decl.rationale}")
        except Exception as exc:  # noqa: BLE001
            store.forget(sid, p_hash)
            proposals.reject_core(sid, proposal["proposal_id"], f"{type(exc).__name__}: {exc}")
            bridge.append_audit(payload, "declare", {
                "decision": "confirmation_core_rejected", "proposal_id": proposal["proposal_id"],
                "retryable": True, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                **audit_common})
            return {"continue": True, "decision": "confirmation_core_rejected"}
        proposals.consume(sid, proposal["proposal_id"], expected_mid)
        bridge.append_audit(payload, "declare", {
            "decision": "proposal_confirmed_applied", "kind": proposal["kind"],
            "proposal_id": proposal["proposal_id"],
            "proposal_source_mid": proposal["source_adapter_message_id"],
            "confirm_mid": expected_mid, "rationale": decl.rationale})
        return {"continue": True, "decision": "proposal_confirmed_applied",
                "kind": proposal["kind"], "proposal_id": proposal["proposal_id"]}

    # ---- a fresh declaration (not a confirmation) ----------------------------
    if open_proposal is not None:
        # The successor message is being used for a NEW intent, not a
        # confirmation: the open proposal dies and the new intent is evaluated
        # below (a confirmation always requires explicit confirm_proposal_id).
        proposals.supersede_open(sid, "successor_message_used_for_new_intent_without_confirmation")

    gated = is_confirm_gated(decl.kind, decl.ambiguity_assessment)
    if gated:
        if not store.declare(sid, p_hash, f"PROPOSAL:{decl.kind}"):
            bridge.append_audit(payload, "declare", {
                "decision": "message_already_declared", **audit_common})
            return {"continue": True, "decision": "message_already_declared"}
        correction_payload = (str(payload.get("payload") or "").strip()
                              if decl.kind == "CORRECTION" else None)
        proposal = proposals.create(
            sid, kind=decl.kind, source_adapter_message_id=expected_mid,
            source_seq=int(record["seq"]), rationale=decl.rationale,
            ambiguity_assessment=decl.ambiguity_assessment,
            impacted_scope=decl.impacted_scope, confidence=decl.confidence,
            correction_payload=correction_payload)
        bridge.append_audit(payload, "declare", {
            "decision": "proposal_created_state_unchanged",
            "proposal_id": proposal["proposal_id"],
            "note": "Core state unchanged until a real confirmation",
            **audit_common})
        return {"continue": True, "decision": "proposal_created_state_unchanged",
                "kind": decl.kind, "proposal_id": proposal["proposal_id"],
                "note": "state unchanged until a real confirmation on the next message"}

    # ---- direct path: CLEAR PAUSE/RESUME on the newest real message -----------
    if not store.declare(sid, p_hash, decl.kind):
        bridge.append_audit(payload, "declare", {
            "decision": "message_already_declared", **audit_common})
        return {"continue": True, "decision": "message_already_declared"}
    declared = AdapterUserOrigin(
        adapter_message_id=expected_mid, session_id=sid, seq=record["seq"],
        prompt_hash=p_hash, prompt_text=record["text"], kind=decl.kind,
        payload=None, declared_by="MODEL_INTERPRETATION_OF_REAL_USER_PROMPT",
        created_at="")
    controller = _controller(payload)
    try:
        _apply_control(controller, payload, decl.kind, declared, revision, state, sid,
                       decl.rationale)
    except Exception as exc:  # noqa: BLE001
        store.forget(sid, p_hash)
        bridge.append_audit(payload, "declare", {
            "decision": "core_rejected", "kind": decl.kind,
            "retryable": True, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            **audit_common})
        return {"continue": True, "decision": "core_rejected",
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
    bridge.append_audit(payload, "declare", {
        "decision": "core_applied_direct_clear",
        "declared_by": "MODEL_INTERPRETATION_OF_REAL_USER_PROMPT", **audit_common})
    return {"continue": True, "decision": "core_applied_direct_clear",
            "kind": decl.kind, "adapter_message_id": expected_mid}


def _sha256_bytes(blob: bytes) -> str:
    import hashlib  # noqa: PLC0415
    return hashlib.sha256(blob).hexdigest()


def _all_contract_items_pass(state: dict) -> tuple[bool, dict]:
    """True only when every contract item is bound to a CURRENT PASS receipt.

    This is the guard for emitting the Controller's final verification bundle:
    the Core hard-codes status=PASS for that bundle, so the Adapter may only
    produce it when the real ledger already proves every acceptance item.

    The conditions mirror the Core's own anti-fake-PASS rule in
    ``delivery_runtime.claim_completion``: bound + CURRENT + PASS evidence, no
    open failures, no open corrections, runtime not in a pre-execution state.
    ``open_blockers`` is deliberately NOT a condition: the Core keeps those
    records for audit and does not feed them into the gate decision.
    """
    items = state.get("contract_runtime_items") or {}
    bindings = state.get("acceptance_bindings") or {}
    runtime = state.get("runtime", {})
    by_id = {e.get("receipt_id"): e for e in runtime.get("evidence_ledger", [])}
    bound, missing, not_pass = [], [], []
    for ac_id, item in items.items():
        receipt_ids = bindings.get(item) or []
        entry = by_id.get(receipt_ids[0]) if receipt_ids else None
        if entry is None:
            missing.append(ac_id)
            continue
        if entry.get("status") != "PASS":
            not_pass.append(ac_id)
            continue
        if entry.get("validation_status") in {"INVALIDATED", "REQUIRES_REVALIDATION"}:
            not_pass.append(ac_id)
            continue
        bound.append({"ac_id": ac_id, "evidence_id": entry.get("evidence_id"),
                      "artifact_path": (entry.get("business_metadata") or {}).get("artifact_path")})
    open_failures = [f.get("failure_id") for f in runtime.get("failures", [])
                     if f.get("status") != "RECOVERED_REVALIDATED"]
    open_corrections = [c.get("correction_id") for c in runtime.get("correction_ledger", [])
                        if c.get("status") != "RESOLVED_REVALIDATED"]
    planning_open = runtime.get("status") in {"PLANNING", "UNDERSTANDING",
                                              "SUSPENDED", "BLOCKED"}
    ok = not (missing or not_pass or open_failures or open_corrections or planning_open)
    return ok, {"bound": bound, "missing": missing, "not_pass": not_pass,
                "open_failures": len(open_failures),
                "open_corrections": len(open_corrections),
                "planning_open": planning_open}


def _maybe_record_final_verification(payload: dict, controller, state_path: Path,
                                     work_id: str) -> dict | None:
    """Emit the Controller-produced final verification bundle, if honestly earned.

    The bundle is assembled mechanically from the real Canonical Evidence Ledger
    (evidence ids + artifact hashes + git head).  It is never prose and never a
    claim the Adapter invented; if any contract item is unbound or not PASS the
    bundle is withheld and the Stop gate keeps refusing completion.
    """
    state = json.loads(state_path.read_text(encoding="utf-8"))
    ok, audit = _all_contract_items_pass(state)
    if not ok:
        bridge.append_audit(payload, "final_verification",
                            {"decision": "withheld_not_all_contract_items_pass", **audit})
        return None
    if any("Final Complete" in k for k in state.get("acceptance_bindings", {})):
        return None  # already emitted for this delivery
    stage = work_id
    bundle = {
        "kind": "FINAL_VERIFICATION_BUNDLE",
        "produced_by": "workbuddy-adapter-bridge",
        "work_id": stage,
        "contract_items": audit["bound"],
        "git": _git_checkpoint(bridge.host_session_id(payload)),
        "produced_at": datetime.now(timezone.utc).isoformat(),
    }
    event = _signed_event(payload, "ArtifactVerified", f"final-verification-{stage[:24]}")
    try:
        controller.record_final_verification(event, work_id=stage, bundle=bundle)
    except Exception as exc:  # noqa: BLE001
        bridge.append_audit(payload, "final_verification",
                            {"decision": "core_rejected",
                             "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        return None
    bridge.append_audit(payload, "final_verification",
                        {"decision": "bundle_recorded", "work_id": stage,
                         "contract_items": len(audit["bound"])})
    return bundle


def cmd_posttooluse() -> dict:
    payload = bridge.read_stdin_payload()
    event_name = payload.get("hook_event_name", "")
    if event_name != "PostToolUse":
        bridge.append_audit(payload, "posttooluse", {"decision": "not_posttooluse"})
        return {"continue": True}
    state_path = _state_file(payload)
    if not state_path.is_file():
        bridge.append_audit(payload, "posttooluse", {"decision": "no_delivery_session"})
        return {"continue": True}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    wu_registry = bridge.bridge_state_dir(payload) / "work-unit-registry.json"
    registry = json.loads(wu_registry.read_text(encoding="utf-8")) if wu_registry.is_file() else {}
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    call_id = str(payload.get("tool_use_id") or payload.get("call_id") or "ptu")
    # find matching work unit by tool + artifact command pattern
    matched = None
    for entry in registry.get("units", []):
        if tool_name != entry.get("tool"):
            continue
        cmd = str(tool_input.get("command") or "")
        pattern = entry.get("command_pattern") or entry.get("artifact_pattern") or ""
        if pattern and re.search(pattern, cmd):
            matched = entry
            break
        # fallback: artifact file in the command that is produced by this unit
    if matched is None:
        bridge.append_audit(payload, "posttooluse",
                            {"decision": "no_registered_work_unit", "tool": tool_name})
        return {"continue": True}
    artifact_rel = str(matched.get("artifact") or "")
    # Same rule as wbbridge.project_root(): under Git Bash CODEBUDDY_PROJECT_DIR
    # can arrive in POSIX form (/c/...) and would resolve to C:\c\..., so the hook
    # process cwd is authoritative.
    artifact_path = bridge.project_root() / artifact_rel
    verifier_id = matched.get("verifier", "suite-pass")
    ac_id = matched["ac_id"]
    # A Core receipt must bind to a REAL plan work item.  The plan for an
    # auto-composed single-stage session names the stage after the user goal;
    # the registry may use the sentinel "__STAGE_0__" for that case.
    work_id = matched.get("work_id", "__STAGE_0__")
    if work_id == "__STAGE_0__":
        stages = state.get("runtime", {}).get("plan", {}).get("stages", [])
        if stages:
            work_id = stages[0].get("name", work_id)
    controller = _controller(payload)
    # verifier registry lives in this Adapter bridge (deterministic, allow-listed)
    def _suite_pass(data: bytes) -> tuple[bool, dict]:
        text = data.decode("utf-8", "replace")
        return ("passed" in text.lower(), {"tail": text.strip().splitlines()[-1][:120] if text.strip() else ""})
    def _verdict_pass(data: bytes) -> tuple[bool, dict]:
        try:
            verdict = json.loads(data.decode("utf-8")).get("verdict")
        except Exception as exc:  # noqa: BLE001
            return False, {"error": str(exc)}
        return verdict == "PASS", {"verdict": verdict}
    verifiers = {"suite-pass": _suite_pass, "verdict-pass": _verdict_pass}
    event = _signed_event(payload, "ArtifactVerified", f"ptu-{call_id[:40]}")
    try:
        controller.record_artifact(event, work_id=work_id, path=artifact_path,
                                   ac_id=ac_id, verifier=verifiers[verifier_id])
    except Exception as exc:  # noqa: BLE001
        bridge.append_audit(payload, "posttooluse",
                            {"decision": "core_rejected", "work_id": work_id,
                             "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        return {"continue": True}
    bridge.append_audit(payload, "posttooluse",
                        {"decision": "receipt_recorded", "work_id": work_id,
                         "ac_id": ac_id, "artifact": artifact_rel})
    # Only once every contract item is proven does the Controller emit its final
    # verification bundle; the Stop gate then has the "Final Complete" evidence.
    _maybe_record_final_verification(payload, controller, state_path, work_id)
    return {"continue": True}


def cmd_stop() -> dict:
    payload = bridge.read_stdin_payload()
    state_path = _state_file(payload)
    if not state_path.is_file():
        bridge.append_audit(payload, "stop", {"decision": "no_delivery_session"})
        return {"continue": True}
    controller = _controller(payload)
    event = _signed_event(payload, "Stop", f"stop-{int(datetime.now(timezone.utc).timestamp())}")

    # A USER pause is authoritative: while the delivery is suspended the Stop
    # event must NOT run the completion gate, because claim_completion would
    # overwrite the SUSPENDED state and make the later USER_RESUME fail with
    # session_not_suspended.  The pause checkpoint stays untouched.
    # Terminal states are equally authoritative: claim_completion would
    # otherwise overwrite CANCELLED / COMPLETED with NOT_COMPLETE just because
    # some evidence is missing.
    try:
        state = controller.restore_state()
        runtime_status = state.get("runtime", {}).get("status")
        has_open_user_pause = bool(state.get("runtime", {}).get("suspensions"))
    except Exception as exc:  # noqa: BLE001
        runtime_status, has_open_user_pause = None, False
        bridge.append_audit(payload, "stop",
                            {"decision": "state_read_error",
                             "error": f"{type(exc).__name__}: {exc}"})
    if runtime_status in {"CANCELLED", "COMPLETED"}:
        bridge.append_audit(payload, "stop", {
            "decision": "gate_skipped_terminal_state",
            "reason": f"delivery already {runtime_status}; completion gate must not run"})
        return {"continue": True, "decision": "continue",
                "reason": f"delivery terminal ({runtime_status}); completion gate skipped"}
    if has_open_user_pause and runtime_status == "SUSPENDED":
        bridge.append_audit(payload, "stop", {
            "decision": "gate_skipped_delivery_suspended",
            "reason": "user pause is authoritative; completion gate must not run while suspended"})
        return {"continue": True, "decision": "continue",
                "reason": "delivery suspended by user; completion gate skipped"}

    try:
        gate = controller.before_completion(event)
    except Exception as exc:  # noqa: BLE001
        bridge.append_audit(payload, "stop",
                            {"decision": "gate_error", "error": f"{type(exc).__name__}: {exc}"})
        return {"continue": True}
    allow = bool(gate.get("allow_completion"))
    bridge.append_audit(payload, "stop", {
        "decision": "gate_allows_completion" if allow else "gate_blocks_completion",
        "completion_status": gate.get("status"),
        "blocker": gate.get("blocker")})
    # Stop hook contract: continue=false tells the agent to keep working when the
    # Core gate refuses completion; continue=true when completion is verified.
    # ENFORCE mode makes the refusal real on the host.  OBSERVE mode (default)
    # records the genuine Core gate decision without locking the conversation,
    # which keeps an in-progress delivery usable while it awaits real user input.
    enforce = os.environ.get("WBFDC_STOP_ENFORCE", "").strip().lower() in {"1", "true", "enforce"}
    if allow:
        return {"continue": True, "decision": "allow"}
    if enforce:
        return {"continue": False,
                "reason": "completion gate refuses delivery close: " +
                          json.dumps(gate.get("blocker"), ensure_ascii=False)[:500]}
    return {"continue": True, "decision": "continue",
            "reason": None,
            "gate_refused": json.dumps(gate.get("blocker"), ensure_ascii=False)[:500]}


def cmd_bootstrap() -> dict:
    payload = bridge.read_stdin_payload()
    cfg = CONFIG
    sid = bridge.host_session_id(payload)
    state_path = _state_file(payload)
    if state_path.is_file():
        return {"decision": "session_exists"}
    goal = os.environ.get("WBFDC_GOAL", "").strip()
    contract_raw = os.environ.get("WBFDC_CONTRACT", "[]")
    contract = json.loads(contract_raw)
    if not goal or not contract:
        raise ValueError("bootstrap requires WBFDC_GOAL and WBFDC_CONTRACT env")
    bridge.ensure_core_scripts(cfg)
    controller = _controller(payload)
    event = _signed_event(payload, "UserPromptSubmit", "bootstrap-goal-1")
    controller.start_session(event, original_user_request=goal,
                             acceptance_contract=contract, auto_approve=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    return {"decision": "session_started", "state": str(state_path)}


DISPATCH = {
    "userpromptsubmit": cmd_userpromptsubmit,
    "declare-control": cmd_declare_control,
    "posttooluse": cmd_posttooluse,
    "stop": cmd_stop,
    "bootstrap": cmd_bootstrap,
}


@bridge.always_exit_zero
def main() -> dict:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in DISPATCH:
        return {"continue": True, "decision": f"unknown_command:{command}"}
    return DISPATCH[command]()


if __name__ == "__main__":
    main()
