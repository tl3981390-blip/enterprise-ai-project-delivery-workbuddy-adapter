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

Run `python src/probe_workbuddy.py --workbuddy-home <path>` before a new-laptop or
customer demonstration.  Its results are deliberately split: formal Core
installation, a fresh-session project-hook check, and automatic Harness-Skill
selection are three separate claims.  Do not present the last two as PASS
unless the probe and the fresh session both produce the required Host evidence.

## Development status

Adapter repository, not a released product. Real WorkBuddy CLI sessions verify
project-scoped UserPromptSubmit/PostToolUse/Stop bridge firing and Core Evidence
receipt recording. This repository is deliberately limited to a **delivery
evidence demonstration**: WorkBuddy does not expose a trustworthy current-session
Skill list to project Hooks, so automatic selection of other WorkBuddy Skills is
`NOT_INCLUDED_BY_DESIGN`. It also does not give the Adapter a Host-enforced model
invocation channel for the separate `declare-control` operation, so full Human
Authority Controller demonstrations remain `PENDING_EXTERNAL_VALIDATION`. The
Adapter fails closed; it does not emulate either missing Host facility. The formal
Core is never modified.

## Branch: `workbuddy-full-delivery-controller` (this branch)

Real, code-level implementation of delivery wiring candidates:

- **Harness Capability Router** (`src/capability_router.py` + `src/harness_skill_snapshot.py`) —
  candidates come ONLY from a Bridge-written, PostToolUse-attested current-session
  skill list; model JSON, disk scans, mock registries and hardcoded names are rejected.
  Selection may precede first invocation, but that invocation remains mandatory before
  callable status is trusted. No eligible match returns `NO_ELIGIBLE_HARNESS_SKILL`.
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
- Earlier automatic-run records remain historical evidence of Hook firing and Core
  receipt behavior, but do **not** prove automatic Skill selection because their
  snapshots lacked Bridge-attested Host provenance. New evidence is accepted only
  through `tools/verify_evidence.py <run-dir>`.

Status: `CANONICAL_EVIDENCE_INTEGRATION` has real-machine evidence. Human Authority
Controller code is covered by deterministic tests, but is not a demonstrated
WorkBuddy Host integration because this Host has not invoked its declaration
channel in a real conversation.
Automatic selection among existing WorkBuddy Skills is **not included in this
WorkBuddy demonstration integration**.  The Host exposes `/skills` only as a
UI/model interaction and does not supply a trustworthy current-session list to
project Hooks.  The adapter therefore never fabricates a list or blocks ordinary
Delivery Core demonstrations on that unavailable Host feature.

## Enterprise demonstration

Use [Enterprise Demonstration and Value Contract](docs/ENTERPRISE_DEMO_AND_VALUE.md)
for the customer-facing value proposition, the evidence boundary, and the
preflight-led demonstration sequence.  It distinguishes the real delivery
controls already demonstrated from automatic use of existing WorkBuddy Skills,
which is deliberately excluded on the current Host build.
