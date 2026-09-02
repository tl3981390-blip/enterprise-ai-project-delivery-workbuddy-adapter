#!/usr/bin/env python3
"""WorkBuddy host-event bridge entry points (Adapter branch, not the Core).

Invoked by the WorkBuddy host through project-scoped command hooks declared in
.codebuddy/settings.local.json (this project).  Each invocation receives the REAL
host event JSON on stdin and maps it into the formally installed Core runtime.

Commands (argv[1]):
  userpromptsubmit   -- REAL UserPromptSubmit -> Human Authority control (if any)
  posttooluse        -- REAL PostToolUse -> canonical evidence receipt
  stop               -- REAL Stop -> Core completion gate
  bootstrap          -- create the delivery session from the registered real goal
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
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


def cmd_userpromptsubmit() -> dict:
    payload = bridge.read_stdin_payload()
    event_name = payload.get("hook_event_name", "")
    prompt = str(payload.get("prompt") or "").strip()
    sid = bridge.host_session_id(payload)
    # -- only REAL host UserPromptSubmit payloads are accepted -----------------
    if event_name != "UserPromptSubmit":
        bridge.append_audit(payload, "userpromptsubmit", {"decision": "not_user_prompt_submit"})
        return {"continue": True}

    # Resolve the delivery session for this host session.
    state_path = _state_file(payload)
    has_session = state_path.is_file()
    if not has_session:
        bridge.append_audit(payload, "userpromptsubmit", {
            "decision": "no_delivery_session",
            "prompt_preview": prompt[:80],
            "hint": "delivery must be started by an adapter bootstrap from the real goal"})
        return {"continue": True}

    state = json.loads(state_path.read_text(encoding="utf-8"))
    revision = state.get("contract_revision", 1)

    # -- classify explicit user controls (exact phrases only) -----------------
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from human_authority import (classify_control, canonical_prompt_hash,  # noqa: PLC0415
                                 PromptStore, ReplayRejected, NotUserOrigin, ControlRejected)
    store = PromptStore(bridge.bridge_state_dir(payload) / "prompt-store.json")

    origin_payload = {"origin": "UserPromptSubmit", "session_id": sid, "prompt": prompt}
    try:
        seq, is_new = store.next(sid, canonical_prompt_hash(prompt))
    except Exception as exc:  # noqa: BLE001
        bridge.append_audit(payload, "userpromptsubmit", {"decision": "store_error",
                                                          "error": str(exc)})
        return {"continue": True}
    if not is_new:
        bridge.append_audit(payload, "userpromptsubmit",
                            {"decision": "replay_rejected", "prompt_hash": canonical_prompt_hash(prompt)[:16]})
        return {"continue": True}

    try:
        kind_and_payload = classify_control(prompt)
    except ControlRejected as exc:
        bridge.append_audit(payload, "userpromptsubmit",
                            {"decision": "control_rejected", "reason": str(exc)})
        return {"continue": True}
    if kind_and_payload is None:
        bridge.append_audit(payload, "userpromptsubmit", {"decision": "ordinary_prompt"})
        return {"continue": True}

    kind, ctrl_payload = kind_and_payload
    event_id = f"am-{sid[:8]}-{seq}-{kind.lower()}"
    controller = _controller(payload)
    try:
        if kind == "PAUSE":
            controller.apply_user_pause(
                _signed_event(payload, "USER_PAUSE", event_id),
                expected_contract_revision=revision,
                reason="user:暂停交付",
                checkpoint_identity=_git_checkpoint(sid),
                evidence_ids=_recent_pass_evidence(state))
        elif kind == "RESUME":
            suspensions = state.get("runtime", {}).get("suspensions", [])
            suspension_id = suspensions[-1]["suspension_id"] if suspensions else None
            if not suspension_id:
                raise KeyError("user_suspension_not_found")
            controller.apply_user_resume(
                _signed_event(payload, "USER_RESUME", event_id),
                expected_contract_revision=revision,
                suspension_id=suspension_id,
                current_identity=_git_checkpoint(sid),
                revalidation_evidence_ids=_recent_pass_evidence(state))
        elif kind == "CANCEL":
            controller.apply_user_cancel(
                _signed_event(payload, "USER_CANCEL", event_id),
                expected_contract_revision=revision)
        elif kind == "CORRECTION":
            controller.apply_user_correction(
                _signed_event(payload, "USER_CORRECTION", event_id),
                expected_contract_revision=revision,
                description=ctrl_payload or "记录纠正",
                violated_requirements=[ctrl_payload or "user correction"],
                root_cause_class="USER_REPORTED",
                related_checks=["user-stated requirement"])
    except Exception as exc:  # noqa: BLE001
        bridge.append_audit(payload, "userpromptsubmit",
                            {"decision": "core_rejected", "kind": kind,
                             "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        return {"continue": True}

    bridge.append_audit(payload, "userpromptsubmit", {"decision": "core_applied",
                                                      "kind": kind, "event_id": event_id})
    return {"continue": True}


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
    artifact_path = Path(os.environ.get("CODEBUDDY_PROJECT_DIR", os.getcwd())) / artifact_rel
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
    return {"continue": True}


def cmd_stop() -> dict:
    payload = bridge.read_stdin_payload()
    state_path = _state_file(payload)
    if not state_path.is_file():
        bridge.append_audit(payload, "stop", {"decision": "no_delivery_session"})
        return {"continue": True}
    controller = _controller(payload)
    event = _signed_event(payload, "Stop", f"stop-{int(datetime.now(timezone.utc).timestamp())}")
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
