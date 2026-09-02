# enterprise-ai-project-delivery-workbuddy-adapter

WorkBuddy-specific integration candidate for the [enterprise-ai-project-delivery Core](https://github.com/tl3981390-blip/enterprise-ai-project-delivery). This repository contains no fork or copy of the Delivery Core.

## Current truth

`CONTROLLER_NOT_CONNECTED` for WorkBuddy full Human Authority control.

WorkBuddy hooks can support project-scoped lifecycle observation, tool-result capture, a persisted bridge state, a Stop/Evidence gate and replay detection. The currently observed Hook contract does not expose a trusted `conversation_id` and `message_id` for user pause, resume, cancel, correction, plan approval or requirement change. Those operations therefore remain fail-closed. A Hook event id may be used for technical replay detection only; it is never treated as user authority.

Do not enable the candidate hooks globally. They are deliberately inert unless a project explicitly opts in, and this repository must not be released as a connected Controller until the conformance probe proves the required host fields and lifecycle events.

## Core compatibility

The adapter is designed for the formal Core release below:

| Field | Value |
| --- | --- |
| Core version | `3.0.6` |
| Tag | `v3.0.6` |
| Commit | `0937642afa0d488b20701c87e2ee3cd2a921cd2d` |
| Asset SHA-256 | `2512a954e1a73e3a6070318d7018ac6424d6904164db19e560f8ba9ec0cd4d5f` |

Run `python src/probe_workbuddy.py --workbuddy-home <path>` before attempting any installation or Hook registration. Only `CONTROLLER_CONNECTED` permits a full-control installation flow.

## Development status

This is an adapter-development repository, not a released WorkBuddy product. It must remain `PENDING_EXTERNAL_VALIDATION` until a real WorkBuddy run proves all controller conformance checks.

## Branch: `workbuddy-full-delivery-controller` (this branch)

Real, code-level implementation of the full delivery wiring:

- **Harness Capability Router** (`src/capability_router.py` + `src/harness_skill_snapshot.py`) —
  candidates come ONLY from the current session's Skill-tool/available_skills snapshot;
  illegal sources (disk scans, mock registries, hardcoded names) are rejected by code.
  Eligibility chain: available -> identity complete -> really-verified callable ->
  permission -> task text overlap. Decision artifact per Work Unit; no eligible match
  returns `NO_ELIGIBLE_HARNESS_SKILL`.
- **Canonical Evidence** (`src/harness_receipts.py`) — HARNESS_EXECUTION receipts only from
  PostToolUse-shaped real tool results; model-built PASS dicts, empty outputs and
  event-level replays are rejected; completion gate reads the ledger only.
- **Human Authority Controller** (`src/human_authority.py`) — adapter_message_id derived
  ONLY from a real UserPromptSubmit payload (session + seq + prompt hash, persisted);
  exact-match user controls 暂停交付/继续交付/取消交付/记录纠正：; model-forged origins,
  replays and other-session origins fail.
- **Scope control** (`src/scope_control.py`) — per-invocation temp context + audit trail;
  contexts are removed after each Work Unit.
- **Live hook caveat**: `hooks/hooks.json` declares candidate UserPromptSubmit/PostToolUse
  hooks but stays INERT (empty arrays, project contract `enabled:false`). Nothing is
  registered globally; live host hook firing remains `PENDING_EXTERNAL_VALIDATION`.

Real acceptance evidence lives in `evidence/full-delivery-controller/2026-09-02/`
(session snapshot, router decision, git-state report from a really-loaded skill, evidence
ledger with 5 receipts, scope audit). Full test suite: 34 passed.

Status of the four product gates:
`AUTOMATIC_HARNESS_SKILL_SELECTION`, `CANONICAL_EVIDENCE_INTEGRATION`,
`WORKBUDDY_HUMAN_AUTHORITY_CONTROLLER`, `FINAL_PRODUCT_TARGET_ON_WORKBUDDY` — see the
delivery report in this session; live-host portions are not claimed as verified here.
