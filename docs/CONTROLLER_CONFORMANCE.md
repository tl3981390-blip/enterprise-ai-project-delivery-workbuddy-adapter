# WorkBuddy Controller Conformance

The adapter may report full `CONTROLLER_CONNECTED` only when WorkBuddy itself supplies and the adapter exercises:

1. a trusted user-origin primitive for each user-controlled transition;
2. distinct host events for user pause, resume, cancel and correction;
3. persistent bridge state; and
4. an enforceable completion interception point.

## What this branch implements (real code)

- **User origin (item 1)**: `human_authority.capture_user_prompt` records the message verbatim (no intent guessing); the model then declares a control via `declare_control`; the adapter_message_id is derived from the real payload
  `adapter_message_id` from a REAL `UserPromptSubmit` hook payload
  (`am-<sha256(session_id|seq|prompt_hash)>-<seq>`). Model text, tool output, Stop and
  PostToolUse can never assert user origin. If the host cannot reliably deliver
  UserPromptSubmit payloads with `session_id` + raw prompt, the honest verdict is
  `BLOCKED_BY_WORKBUDDY_CAPABILITY` / `PENDING_EXTERNAL_VALIDATION` — never a fabricated
  `CONTROLLER_CONNECTED`.
- **Evidence (item 4)**: `harness_receipts.EvidenceLedger.completion_gate` is the
  enforceable completion check and reads the ledger of HARNESS_EXECUTION receipts only.
- **Hooks**: `hooks/hooks.json` declares candidate `UserPromptSubmit`/`PostToolUse`/`Stop`
  hooks but is deliberately INERT (empty arrays, project contract `enabled:false`).
  No configuration in this repository registers hooks globally or changes WorkBuddy settings.

## Current status

Project-scoped Host-event wiring is real: WorkBuddy CLI sessions fed live
UserPromptSubmit/PostToolUse/Stop payloads through the bridge. The complete
`CONTROLLER_CONNECTED` claim is **not** currently available because automatic
Skill selection lacks a Host-attested available-skills receipt. `hooks/hooks.json` remains
inert; real activation is project-scoped via
`<project>/.codebuddy/settings.local.json`.  Nothing is registered globally and
WorkBuddy global settings are unmodified (SHA verified in the run evidence).
