# WorkBuddy Controller Conformance

The adapter may report full `CONTROLLER_CONNECTED` only when WorkBuddy itself supplies and the adapter exercises:

1. a trusted user-origin primitive for each user-controlled transition;
2. distinct host events for user pause, resume, cancel and correction;
3. persistent bridge state; and
4. an enforceable completion interception point.

## What this branch implements (real code)

- **User origin (item 1)**: `human_authority.originate_user_prompt` derives a persistent
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

`CONTROLLER_NOT_CONNECTED` (full-control claim) until a real host run feeds live
UserPromptSubmit/PostToolUse payloads through the implemented handlers. Everything that can
be proven without host firing is proven: 34 automated tests green, plus real end-to-end
evidence in `evidence/full-delivery-controller/2026-09-02/`.
