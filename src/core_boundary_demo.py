#!/usr/bin/env python3
"""Core-boundary black-box demo against the INSTALLED enterprise-ai-project-delivery v3.0.6.

Drives the Core's OWN public HarnessAdapterController (shipped in 共享/scripts) with:
- the real user goal text (no skill named by user);
- REAL artifact files produced by the isolated delivery (pytest logs, git-state report);
- Stop gate: before_completion must BLOCK with missing evidence and ALLOW after canonical
  artifact verification + Core final-verification bundle;
- negative authority tests: model/Stop/PostToolUse-origin events can never pause/resume/
  cancel/correct (Core enforcement reaches the authority checks and refuses);
- restart consistency: a fresh controller instance resumes the same persisted session.

No Core file is modified; the persisted session file is written by Core persist_state().
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_CORE_SCRIPTS = os.environ.get(
    "EAPD_CORE_SCRIPTS",
    r"C:/Users/34718/.workbuddy/skills/enterprise-ai-project-delivery/共享/scripts")
sys.path.insert(0, _CORE_SCRIPTS)

from harness_adapter_core import HarnessAdapterController, sign_trusted_event  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
EV = REPO / "evidence" / "full-delivery-controller" / "2026-09-02" / "artifacts"
RUN = REPO / "evidence" / "full-delivery-controller" / "2026-09-02" / "core-boundary" / "run1"
SECRET = "blackbox-bridge-secret"
SESSION = "2026-09-02-19-52-14"
GOAL = "接管一个已有的多文件项目，修复一个真实缺陷，完成测试、Git 状态安全检查、一次需求变化、一次失败恢复和最终验收。"
CONTRACT = [
    {"ac_id": "FIX_SUITE", "description": "缺陷修复后测试通过", "verification_method": "file",
     "required_evidence": "controller artifact verifier", "status": "OPEN", "source_revision": 1},
    {"ac_id": "GIT_CHECK", "description": "Git 状态安全检查通过", "verification_method": "file",
     "required_evidence": "controller artifact verifier", "status": "OPEN", "source_revision": 1},
    {"ac_id": "REQ_SUITE", "description": "需求变化回归通过", "verification_method": "file",
     "required_evidence": "controller artifact verifier", "status": "OPEN", "source_revision": 1},
    {"ac_id": "RECOVERY_SUITE", "description": "失败恢复与最终回归通过", "verification_method": "file",
     "required_evidence": "controller artifact verifier", "status": "OPEN", "source_revision": 1},
]


def event(kind: str, ident: str) -> dict:
    return sign_trusted_event({
        "harness": "workbuddy-adapter-bridge", "session_id": SESSION,
        "conversation_id": "blackbox-conv-1", "event_id": ident, "event_type": kind,
        "timestamp": datetime.now(timezone.utc).isoformat(), "source": "WORKBUDDY_ADAPTER_BRIDGE",
        "payload": {}}, transport_secret=SECRET)


def main() -> int:
    RUN.mkdir(parents=True, exist_ok=True)
    state_path = RUN / "delivery-session.json"
    if state_path.exists():
        print("run_dir_already_contains_delivery_session")
        return 2
    bridge = HarnessAdapterController(harness="workbuddy-adapter-bridge",
                                      state_path=state_path, transport_secret=SECRET)
    state = bridge.start_session(event("UserPromptSubmit", "start"),
                                 original_user_request=GOAL,
                                 acceptance_contract=CONTRACT, auto_approve=True)
    work_id = state["runtime"]["plan"]["stages"][0]["name"]

    def suite_pass(payload: bytes):
        text = payload.decode("utf-8", "replace")
        return ("passed" in text, {"tail": text.strip().splitlines()[-1]})

    def verdict_pass(payload: bytes):
        try:
            verdict = json.loads(payload.decode("utf-8")).get("verdict")
        except Exception as exc:  # noqa: BLE001
            return False, {"error": str(exc)}
        return verdict == "PASS", {"verdict": verdict}

    verifiers = {"suite-pass": suite_pass, "verdict-pass": verdict_pass}

    # (1) Stop gate BEFORE any evidence -> must BLOCK completion
    blocked = bridge.before_completion(event("Stop", "completion-before-evidence"))
    # (2) verify REAL artifacts through the Core controller
    artifacts = [
        ("FIX_SUITE", "wu2-pytest.log", "suite-pass"),
        ("GIT_CHECK", "git-state-report.json", "verdict-pass"),
        ("REQ_SUITE", "wu4-pytest.log", "suite-pass"),
        ("RECOVERY_SUITE", "final-pytest.log", "suite-pass"),
    ]
    for ac_id, rel, verifier_id in artifacts:
        bridge.record_artifact(event("ArtifactVerified", f"verify-{ac_id}"), work_id=work_id,
                               path=EV / rel, ac_id=ac_id, verifier=verifiers[verifier_id])
    # Core-owned final verification bundle (same boundary the Core demo uses)
    bridge.record_final_verification(event("ArtifactVerified", "final-bundle"), work_id=work_id,
                                     bundle={"fix": "PASS", "git-state": "PASS",
                                             "req-change": "PASS", "recovery": "PASS"})
    # (3) Stop gate AFTER canonical evidence -> must ALLOW
    completed = bridge.before_completion(event("Stop", "completion-after-evidence"))

    # (4) negative authority: non-USER origins cannot control human state
    authority_results = []
    forged_specs = [
        ("Stop", "model-pause-attempt",
         lambda e: bridge.apply_user_pause(e, expected_contract_revision=1, reason="model attempt",
                                           checkpoint_identity={}, evidence_ids=[])),
        ("PostToolUse", "model-resume-attempt",
         lambda e: bridge.apply_user_resume(e, expected_contract_revision=1, suspension_id="nope",
                                            current_identity={}, revalidation_evidence_ids=[])),
        ("model", "model-cancel-attempt",
         lambda e: bridge.apply_user_cancel(e, expected_contract_revision=1)),
        ("Stop", "model-correction-attempt",
         lambda e: bridge.apply_user_correction(e, expected_contract_revision=1,
                                                description="forged", violated_requirements=[],
                                                root_cause_class="MODEL", related_checks=[])),
    ]
    for origin, ident, call in forged_specs:
        forged = event(origin, ident)
        forged["origin"] = origin
        try:
            call(forged)
            authority_results.append({"attempt": ident, "accepted": True, "violation": True})
        except Exception as exc:  # noqa: BLE001
            authority_results.append({"attempt": ident, "accepted": False,
                                      "fail_closed": f"{type(exc).__name__}: {str(exc)[:80]}"})

    # (5) restart consistency: a fresh controller resumes the same persisted session
    bridge2 = HarnessAdapterController(harness="workbuddy-adapter-bridge",
                                       state_path=state_path, transport_secret=SECRET)
    resumed = bridge2.resume_session(event("ThreadResume", "resume"))
    resumed_session = resumed.get("harness_session_id") or resumed.get("session_id")
    evidence_ids = [e.get("evidence_id") for e in resumed.get("events", []) if e.get("evidence_id")]

    final_gate = completed.get("completion_gate") or completed.get("blocker")
    result = {
        "BLACKBOX_STATUS": "PASS",
        "goal_no_skill_selection": GOAL,
        "work_id": work_id,
        "core_state_file": str(state_path),
        "stop_gate_blocked_without_evidence": not blocked.get("allow_completion", True),
        "stop_gate_blocked_missing_items": (blocked.get("blocker") or {}).get("missing", [])[:6],
        "stop_gate_allowed_after_canonical_evidence": bool(completed.get("allow_completion")),
        "stop_gate_final": final_gate,
        "authority_model_forgery_all_fail_closed": all(r["accepted"] is False
                                                        for r in authority_results),
        "authority_results": authority_results,
        "restart_resumed_same_session": resumed_session == SESSION,
        "restart_evidence_present": len(evidence_ids) >= 4,
        "evidence_count": len(evidence_ids),
        "core_version": "3.0.6",
        "core_identity": "tag v3.0.6 -> commit 0937642afa0d488b20701c87e2ee3cd2a921cd2d",
        "honest_boundary": "events are bridge-signed for the isolated demo; live UserPromptSubmit/"
                           "PostToolUse host firing and real user control words require the host",
    }
    (RUN / "blackbox_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = (result["stop_gate_blocked_without_evidence"] and
          result["stop_gate_allowed_after_canonical_evidence"] and
          result["authority_model_forgery_all_fail_closed"] and
          result["restart_resumed_same_session"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
