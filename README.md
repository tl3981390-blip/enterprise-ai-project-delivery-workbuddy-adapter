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
    classifies or changes state by itself; the returned `[delivery-control]`
    note carries the `adapter_message_id`.
  - `declare-control` — the model's governed channel: it looks the message up in
    the prompt store (must be a real capture), refuses undeclared/duplicate/
    forged/channel-wrong/other-session/stale declarations.  CANCEL, CORRECTION
    and any AMBIGUOUS reading only open a Proposal; a Proposal is applied to the
    Core only after the immediately-following real message confirms it
    (`confirm_proposal_id`, same kind, CLEAR).  Only CLEAR PAUSE/RESUME apply
    directly.

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

Adapter repository, not a released product.  As of the 2026-09-02 automatic
black-box acceptance (`evidence/auto-blackbox/run-20260902T170022Z`), the real
host wiring is verified end-to-end on real WorkBuddy CLI sessions with official
project-scoped command hooks (see below).  The formal Core is never modified.

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
  ONLY from a real UserPromptSubmit payload (session + seq + prompt hash, persisted).
  Two-stage authority: CANCEL/CORRECTION and any AMBIGUOUS reading open a Proposal
  (`proposals.json`) and never touch the Core; only CLEAR PAUSE/RESUME apply directly;
  a Proposal is confirmed only by the immediately-following REAL message of the same
  session (same kind, CLEAR, once).  Forged origins, wrong channels, replays,
  other-session/stale declarations all fail closed (`bridge.py declare-control`).
- **Scope control** (`src/scope_control.py`) — per-invocation temp context + audit trail;
  contexts are removed after each Work Unit.
- **Live hooks**: `hooks/hooks.json` stays inert by design.  Real activation is
  project-scoped: `<project>/.codebuddy/settings.local.json` registers the three
  command hooks (UserPromptSubmit/PostToolUse/Stop) that execute
  `hooks/bridge/bridge.py`.  Nothing is registered globally; WorkBuddy global
  settings/plugins/skill directories are untouched (SHA verified in the run evidence).

Real acceptance evidence:
- `evidence/full-delivery-controller/2026-09-02/` — earlier real desktop-session runs.
- `evidence/auto-blackbox/run-20260902T170022Z/` — automatic REAL black-box run
  (real CLI sessions, real hooks, real Core v3.0.6 ledger), 23/23 assertions PASS:
  bootstrap, receipts, skill auto-select + real invocation, two-stage Human
  Authority suite, Stop gate deny→allow, second-session isolation/replay/persistence,
  scope cleanup.  See `evidence/auto-blackbox/README.md`.

Status of the four product gates: `AUTOMATIC_HARNESS_SKILL_SELECTION`,
`CANONICAL_EVIDENCE_INTEGRATION`, `WORKBUDDY_HUMAN_AUTHORITY_CONTROLLER`,
`FINAL_PRODUCT_TARGET_ON_WORKBUDDY` — real-machine automated evidence in
`evidence/auto-blackbox/`; live-desktop portions remain covered by the real-session
evidence under `evidence/full-delivery-controller/2026-09-02/real-session/`.
