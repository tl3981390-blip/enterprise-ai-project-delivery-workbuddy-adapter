# enterprise-ai-project-delivery-workbuddy-adapter

WorkBuddy-specific integration candidate for the [enterprise-ai-project-delivery Core](https://github.com/tl3981390-blip/enterprise-ai-project-delivery). This repository contains no fork or copy of the Delivery Core.

## Design: the skill governs the model, it never guesses intent

- **Intent recognition belongs to the MODEL** (the agent in the conversation).
  Real users say "停停停", "先别干了", "算了" — not canned phrases. The adapter
  must not hardcode "what users mean".
- **The Adapter/Skill governs the model**: a delivery control
  (PAUSE / RESUME / CANCEL / CORRECTION) may only be *declared* on a user
  message that the host **actually captured verbatim** (a real
  `UserPromptSubmit`). The declaration, the model's rationale and the original
  user text are all audited, so the human can verify or reject the model's
  interpretation. Model prose, tool output and Stop events can never create
  authority.
- The bridge therefore exposes:
  - `userpromptsubmit` — captures one real user message verbatim; **never**
    classifies or changes state by itself.
  - `declare-control` — the model's governed channel: it looks the message up in
    the prompt store (must be a real capture), refuses undeclared/duplicate
    declarations, then asks the Core to apply the control.

## Historical note (pre-2026-09-02 22:00)

Earlier text on this page claimed `CONTROLLER_NOT_CONNECTED` and that hooks must
stay inert. That was superseded by the real host-event bridge implementation on
this branch (see `docs/WORKBUDDY_HOST_EVENT_BRIDGE.md`): the WorkBuddy host
demonstrably executes project-scoped command hooks, and real
PostToolUse/UserPromptSubmit events entered the formal Core v3.0.6. Global
WorkBuddy settings/plugins/skills are untouched.

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
