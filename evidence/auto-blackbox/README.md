# Automatic REAL Hook black-box acceptance — run evidence

Run directory: `evidence/auto-blackbox/run-20260902T170022Z/` (this folder is the
canonical machine evidence set for the automatic black-box acceptance of the
WorkBuddy full-delivery-controller bridge).

## How the run was driven (no user participation)

The driver `tools/run_blackbox.py` builds a disposable isolated project under
`%TEMP%\wbfdc-bb-20260902T170022Z` with official project-scoped command hooks
(`.codebuddy/settings.local.json` → `hooks/bridge/bridge.py`) and then drives
REAL WorkBuddy CLI sessions (the officially installed `@genie/agent-cli`
v2.137.1 inside the WorkBuddy install, `-p --session-id --continue
--dangerously-skip-permissions --output-format json`).  Every prompt is a real
`UserPromptSubmit`, every tool call a real `PostToolUse`, every turn end a real
`Stop`; nothing here fabricates a host payload.

Reproduce with:

```
python tools/run_blackbox.py all
```

(assertions are idempotent per run directory; partial phases: `m|h|i|o`).

## Evidence files in this folder

| file | meaning |
| --- | --- |
| `results.json` | per-turn records (prompt, rc, tool calls, assistant tail) + every assertion verdict (`assert::*`) + global settings sha before/after + `overall_pass` |
| `transcripts/` | raw CLI transcripts per session/turn (function calls incl. the real Skill invocation) |
| `audit-wbfdc-m1.jsonl` / `-ha1` / `-iso2` | immutable bridge audit: every host event → decision (per host session) |
| `state-wbfdc-m1.json` | formal Core v3.0.6 delivery session (canonical evidence ledger, bindings, completion gate) |
| `state-wbfdc-ha1.json` | authority session (pause/resume/correction/cancel events, corrections, terminal cancel) |
| `proposals.json` | Adapter proposal ledger (PROPOSED_CONTROL lifecycle) |
| `artifacts/` | real artifacts the receipts bind to: git-state-report.json, canonical-pytest.log (46 passed), git-state-skill-report.json, available-skills-snapshot.json (source=skill_tool_available_skills), router.decision.json (decision=git-state-change-regression) |
| `scope-audit.jsonl` | real ScopeControl open/close cleanup audit |

## Assertions (all PASS, 23/23)

Phase M (main delivery session `wbfdc-m1`):

- `m1-goal` bootstrap from the REAL first user message + Stop gate DENY #1 (no evidence; `gate_blocks_completion`).
- `m2-receipts` two real receipts (git-state-report + canonical pytest log) bound PASS in the formal Core Evidence Ledger.
- `m3-skill` real Skill-tool invocation of `git-state-change-regression`, real `available_skills` snapshot (source=`skill_tool_available_skills`), real router decision (`git-state-change-regression`), real skill-report artifact, final-verification bundle recorded, Stop gate ALLOW → `VERIFIED_DELIVERY_COMPLETE`.

Phase H (authority session `wbfdc-ha1`, two-stage Human Authority):

- `h1-goal` bootstrap; `h1b-evidence` ≥1 real PASS receipt (Core suspend/resume require revalidation evidence).
- `h2-forge` fabricated user message refused (`no_matching_captured_message`); wrong channel (`hook_event_name=Stop`) refused (`declaration_invalid`).
- `h3` ambiguous “先这样吧，先停一下” → only a PAUSE Proposal; Core state unchanged.
- `h4` intervening message keeps the proposal pending; `h5` stale confirmation → rejected (`confirmation_rejected`, proposal EXPIRED at capture).
- `h6` fresh ambiguous pause opens Proposal #2; `h7` confirmation on the immediately following REAL message → Core `USER_PAUSE_APPLIED` (SUSPENDED).
- `h8` model self-resume (invented message) refused; still SUSPENDED.
- `h9` “你确定要取消整个交付吗？” never cancels; only an AMBIGUOUS CANCEL proposal opened.
- `h10` real user resume (CLEAR, new real message) → `USER_RESUME_APPLIED`; stale CANCEL proposal superseded.
- `h11` vague correction → CORRECTION proposal only, `contract_revision`/baseline untouched; `h12` confirmation → `USER_CORRECTION_APPLIED`; `h13` replay confirmation refused (proposal consumed).
- `h14` CANCEL declaration → proposal only (not terminal); `h15` confirmation → `USER_CANCEL_APPLIED`, delivery CANCELLED.
  All four Core authority events carry the confirming real message id:
  `USER_PAUSE_APPLIED am-e3a83f…-8`, `USER_RESUME_APPLIED am-3ba1da…-11`,
  `USER_CORRECTION_APPLIED am-ae13bf…-13`, `USER_CANCEL_APPLIED am-4f67d7…-16`.

Phase I (second isolated session `wbfdc-iso2`, same project):

- `i1-cross-session` second session cannot revive the main session's authority (`cross_session_control_rejected`, newest-session guard) while main session persists `VERIFIED_DELIVERY_COMPLETE`.
- `i2-replay` byte-identical second message → capture refused (ReplayRejected), session seq frozen at 1.
- `i3-persistence` main session state stays VERIFIED; the second session has no own delivery state.

Phase O: `scope-cleanup` real ScopeControl opened/closed twice, contexts removed, `scope-audit.jsonl` appended.

## Hook event → Adapter → Core audit mapping (M session, condensed)

| host event (real) | bridge decision | Core operation | ledger |
| --- | --- | --- | --- |
| UserPromptSubmit (seq 1 goal) | `bootstrap` `session_started_from_real_first_user_prompt` | `start_session` (+approve) | state created |
| PostToolUse Bash `run-git-state-report.sh` | `posttooluse` `receipt_recorded` ac=REAL_HOST_EVENT_BRIDGE | `record_artifact` (verdict PASS) | evidence `workbuddy:ptu-call_00_WgJZG…` PASS |
| PostToolUse Bash `run-canonical-pytest.sh` | `posttooluse` `receipt_recorded` ac=CANONICAL_EVIDENCE_LEDGER | `record_artifact` (suite PASS) | evidence `workbuddy:ptu-call_00_z6kNU…` PASS |
| Skill `git-state-change-regression` + Bash `run-skill-git-report.sh` | `posttooluse` `receipt_recorded` ac=HARNESS_SKILL_SELECTION | `record_artifact` (verdict PASS) | evidence `workbuddy:ptu-call_00_tMaiO…` PASS |
| PostToolUse (last registered) | `final_verification` `bundle_recorded` | `record_final_verification` | evidence `workbuddy:final-verification-…` PASS binds the 3 “证明 Final Complete 的 Evidence” items |
| Stop (turn end) | `stop` `gate_allows_completion` | `before_completion`→`claim_completion` | completion_status `VERIFIED_DELIVERY_COMPLETE`, gate pass True |

## Global configuration integrity

- `~/.workbuddy/settings.json` SHA-256 before `656a132c…` = after `656a132c…` (unchanged; no hooks added globally; hookify not enabled).
- No modification to the installed Core (`~/.workbuddy/skills/enterprise-ai-project-delivery`); the bridge only imports its runtime. The isolated-project hooks run python with `-B` so no bytecode is written into the Core scripts.
- No merge of `main`, no Release published.
