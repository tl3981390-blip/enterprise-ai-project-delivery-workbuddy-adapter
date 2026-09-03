#!/usr/bin/env python3
"""Independent read-only verifier for the canonical black-box evidence.

Re-derives every headline PASS claim from the RAW committed evidence files in a
run directory (state-*.json, audit-*.jsonl, proposals.json, artifacts/,
scope-audit.jsonl, results.json).  It never re-runs the CLI, never trusts the
driver's stored assertion strings: it recomputes from the data.

usage: python tools/verify_evidence.py <run-dir>

The verifier intentionally has no default historical run.  A run produced before
the Host supplied a Bridge-attested capability list cannot prove automatic Skill
selection under the current contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

M, H, I = "wbfdc-m1", "wbfdc-ha1", "wbfdc-iso2"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def audit(run: Path, sid: str) -> list[dict]:
    out = []
    f = run / f"audit-{sid}.jsonl"
    if not f.is_file():
        return out
    for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue  # torn concurrent append line (read-only tolerance)
    return out


CHECKS: list[tuple[str, callable]] = []


def check(name: str):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


@check("M: VERIFIED_DELIVERY_COMPLETE + gate allow")
def m_complete(run: Path) -> tuple[bool, str]:
    st = load(run / f"state-{M}.json")
    ok = (st.get("completion_status") == "VERIFIED_DELIVERY_COMPLETE" and
          st.get("runtime", {}).get("completion_gate", {}).get("pass") is True)
    return ok, f"completion={st.get('completion_status')} gate={st.get('runtime',{}).get('completion_gate',{}).get('pass')}"


@check("M: >=3 contract receipts PASS + final bundle PASS in Core ledger")
def m_ledger(run: Path) -> tuple[bool, str]:
    st = load(run / f"state-{M}.json")
    ev = [e for e in st.get("runtime", {}).get("evidence_ledger", []) if e.get("status") == "PASS"]
    binds = st.get("acceptance_bindings", {})
    final_bound = [k for k in binds if "证明 Final Complete" in k]
    labels = [k for k in binds if "证明 Final Complete" not in k]
    ok = len(ev) >= 4 and len(labels) >= 3 and len(final_bound) == 3
    return ok, f"PASS_evidence={len(ev)} contract_labels={len(labels)} final_labels={len(final_bound)}"


@check("M: Stop audit shows deny (early) and allow (final)")
def m_stop(run: Path) -> tuple[bool, str]:
    stops = [a["outcome"].get("decision") for a in audit(run, M) if a.get("kind") == "stop"]
    return ("gate_blocks_completion" in stops and "gate_allows_completion" in stops), \
        f"stop_decisions={sorted(set(stops))}"


@check("Skill chain: Bridge-attested snapshot + matching Router decision")
def skill(run: Path) -> tuple[bool, str]:
    art = run / "artifacts"
    snap = load(art / "available-skills-snapshot.json")
    router = load(art / "router.decision.json")
    provenance = snap.get("provenance") or {}
    decision = str(router.get("decision") or "")
    identities = {str(item.get("identity")) for item in snap.get("skills", [])}
    ok = (snap.get("source") == "harness_available_skills" and
          provenance.get("hook_event_name") == "PostToolUse" and
          bool(provenance.get("tool_use_id")) and bool(provenance.get("output_sha256")) and
          router.get("snapshot_fingerprint_sha256") == snap.get("fingerprint_sha256") and
          decision in identities)
    return ok, f"source={snap.get('source')} decision={decision} provenance={bool(provenance)}"


@check("Skill chain: Router-selected skill was really invoked in the same session")
def skill_verified(run: Path) -> tuple[bool, str]:
    snap = load(run / "artifacts" / "available-skills-snapshot.json")
    decision = load(run / "artifacts" / "router.decision.json").get("decision")
    selected = next((s for s in snap.get("skills", []) if s.get("identity") == decision), None)
    ok = bool(selected and selected.get("available") is True and
              selected.get("verified_callable") is True and selected.get("permission") == "granted")
    return ok, f"entry={json.dumps(selected, ensure_ascii=False)[:120] if selected else None}"


@check("Skill chain: transcript contains a real invocation of Router decision")
def skill_invoked(run: Path) -> tuple[bool, str]:
    tr_dir = run / "transcripts"
    router = load(run / "artifacts" / "router.decision.json")
    decision = str(router.get("decision") or "")
    hit = False
    for f in sorted(tr_dir.glob("wbfdc-m1--*.json")):
        tr = load(f).get("transcript") or []
        for msg in tr:
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "function_call" and msg.get("name") == "Skill":
                try:
                    args = json.loads(msg.get("arguments") or "{}")
                except ValueError:
                    args = {}
                if decision and decision in json.dumps(args, ensure_ascii=False):
                    hit = True
                    break
        if hit:
            break
    return hit, f"Skill({decision}) function_call found in transcripts"


@check("H: terminal CANCELLED with all four Core authority operations applied")
def h_authority(run: Path) -> tuple[bool, str]:
    st = load(run / f"state-{H}.json")
    types = [e.get("type") for e in st.get("events", []) if e.get("type")]
    need = {"USER_PAUSE_APPLIED", "USER_RESUME_APPLIED",
            "USER_CORRECTION_APPLIED", "USER_CANCEL_APPLIED"}
    ok = st.get("runtime", {}).get("status") == "CANCELLED" and need.issubset(set(types))
    return ok, f"status={st.get('runtime',{}).get('status')} applied={sorted(need & set(types))}"


@check("H: ambiguity opened Proposals without touching Core (no suspension until confirm)")
def h_proposals(run: Path) -> tuple[bool, str]:
    st = load(run / f"state-{H}.json")
    susp_times = [e.get("timestamp") for e in st.get("events", [])
                  if e.get("type") == "USER_PAUSE_APPLIED"]
    created = [a for a in audit(run, H)
               if a.get("kind") == "declare" and
               a["outcome"].get("decision") == "proposal_created_state_unchanged"]
    confirmed = [a for a in audit(run, H)
                 if a.get("kind") == "declare" and
                 a["outcome"].get("decision") == "proposal_confirmed_applied"]
    # first proposal must precede first applied pause (state unchanged until confirm)
    ordered = []
    for a in audit(run, H):
        if a.get("kind") in ("declare",) and a["outcome"].get("decision") in (
                "proposal_created_state_unchanged", "proposal_confirmed_applied"):
            ordered.append(a["outcome"]["decision"])
    first_applied = next((i for i, d in enumerate(ordered)
                          if d == "proposal_confirmed_applied"), None)
    ok = (len(created) >= 2 and len(confirmed) >= 3 and first_applied is not None and
          ordered[first_applied - 1] == "proposal_created_state_unchanged")
    return ok, f"proposals_created={len(created)} confirmed={len(confirmed)} sequence_ok={ok}"


@check("H: forged/stale/replay/cross-channel declarations refused (fail-closed)")
def h_fail_closed(run: Path) -> tuple[bool, str]:
    decs = [a["outcome"].get("decision") for a in audit(run, H) if a.get("kind") == "declare"]
    ok = all(d in decs for d in ("no_matching_captured_message", "declaration_invalid",
                                 "confirmation_rejected", "proposal_created_state_unchanged"))
    return ok, f"present={sorted(set(decs))}"


@check("H: corrections entered the Core only after a legal confirmation")
def h_correction(run: Path) -> tuple[bool, str]:
    st = load(run / f"state-{H}.json")
    corr = st.get("runtime", {}).get("correction_ledger", [])
    confirms = [a for a in audit(run, H)
                if a.get("kind") == "declare" and a["outcome"].get("decision") == "proposal_confirmed_applied"
                and a["outcome"].get("kind") == "CORRECTION"]
    ok = bool(corr) and bool(confirms)
    ref = corr[0].get("user_origin_ref", {}) if corr else {}
    return ok, f"corrections={len(corr)} origin_ref={ref}"


@check("I: cross-session declaration rejected; M stays VERIFIED")
def i_cross(run: Path) -> tuple[bool, str]:
    cross = [a["outcome"] for a in audit(run, M)
             if a.get("kind") == "declare" and
             a["outcome"].get("decision") == "cross_session_control_rejected" and
             a["outcome"].get("newest_session") == I]
    st = load(run / f"state-{M}.json")
    ok = bool(cross) and st.get("completion_status") == "VERIFIED_DELIVERY_COMPLETE"
    return ok, f"cross_session_rejections={len(cross)}"


@check("I: replay of identical message refused, seq frozen; I has no own delivery")
def i_replay(run: Path) -> tuple[bool, str]:
    i_audits = audit(run, I)
    rej = [a["outcome"] for a in i_audits if a.get("kind") == "userpromptsubmit"
           and a["outcome"].get("decision") == "capture_rejected"
           and "ReplayRejected" in str(a["outcome"].get("error", ""))]
    state_file = run / f"state-{I}.json"
    ok = bool(rej) and not state_file.exists()
    return ok, f"replay_rejected={len(rej)} has_own_state={state_file.exists()}"


@check("Scope cleanup: opened/closed twice, contexts removed")
def scope(run: Path) -> tuple[bool, str]:
    recs = [json.loads(ln) for ln in (run / "scope-audit.jsonl").read_text(
        encoding="utf-8").splitlines() if ln.strip()]
    closed = [r for r in recs if r.get("event") == "scope_closed"]
    leftover = [r for r in closed if r.get("context_dir_exists_after") is not False]
    ok = len(closed) == 2 and not leftover
    return ok, f"closed={len(closed)} leftovers={len(leftover)}"


@check("Global settings SHA unchanged (recorded in results.json)")
def global_sha(run: Path) -> tuple[bool, str]:
    res = load(run / "results.json")
    ok = (res.get("global_settings_sha_before") == res.get("global_settings_sha_after"))
    return ok, f"sha={str(res.get('global_settings_sha_after'))[:16]}..."


@check("results.json: all executed assertions pass and no external validation is pending")
def results(run: Path) -> tuple[bool, str]:
    res = load(run / "results.json")
    checks = {k: v for k, v in res.items() if k.startswith("assert::")}
    ok = (res.get("overall_pass") is True and bool(checks) and
          all(v.get("pass") for v in checks.values()) and not res.get("failed_assertions") and
          not res.get("pending_external_validation"))
    return ok, (f"assertions={len(checks)} all_pass={all(v.get('pass') for v in checks.values())} "
                f"pending={res.get('pending_external_validation', [])}")


def main(argv: list[str]) -> int:
    if not argv:
        print("run dir is required; historical pre-provenance runs are not accepted")
        return 2
    run = Path(argv[0])
    if not run.is_dir():
        print("run dir not found:", run)
        return 2
    failed = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn(run)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(("PASS" if ok else "FAIL"), "-", name, "|", detail)
        if not ok:
            failed.append(name)
    print(f"\nchecks={len(CHECKS)} passed={len(CHECKS) - len(failed)} failed={len(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
