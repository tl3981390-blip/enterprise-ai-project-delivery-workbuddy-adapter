# Canonical Evidence & Human Authority (WorkBuddy wiring)

## HARNESS_EXECUTION receipts

`harness_receipts.py` implements the canonical evidence path:

    real WorkBuddy Tool/Skill invocation result
        -> PostToolUse hook payload (hook_origin = "PostToolUse")
        -> receipt_from_posttooluse(...)
        -> EvidenceLedger.append(...)
        -> completion_gate(...)

Hard rules, enforced in code:

- `receipt_from_posttooluse` refuses any payload whose `hook_origin` is not `PostToolUse`
  (Stop, model text, tool output, fake origins all raise `ReceiptRejected`).
- The receipt's `output_sha256` is computed from the real captured output; self-declared
  verdicts (`PASS`/`OK`/`SUCCESS`/`{}`) and empty outputs are rejected.
- The ledger rejects: other-session files, duplicate `receipt_id`, and **event-level replay**
  (same `tool_use_id` + same output digest re-entered, even under a different chain link).
- `completion_gate` reads the ledger only; a log file existing on disk is never evidence.
  Missing required (work_unit, skill) pairs make the gate return `(False, missing)`.

## Adapter User Origin (UserPromptSubmit)

`human_authority.py` derives a persistent, auditable, model-unforgeable
`adapter_message_id` from a **real UserPromptSubmit payload**:

    adapter_message_id = am-<sha256(session_id | seq | prompt_hash)[:32]>-<seq>

- Only `origin == "UserPromptSubmit"` with a host `session_id` and raw `prompt` may assert
  user origin. Model text, tool output, Stop and PostToolUse can never.
- Intent recognition is the MODEL's job (no phrase table).  The bridge governs the model:
  a declaration must reference a REAL captured message with the recomputed
  `adapter_message_id`, the newest capture of the session that owns the newest capture
  overall.  CANCEL, CORRECTION and any AMBIGUOUS reading open a Proposal
  (`proposals.json`); the Core is only touched after the immediately-following REAL
  message confirms the Proposal (same kind, CLEAR, once).  Only CLEAR PAUSE/RESUME apply
  directly.  Vague phrasing and inferred intent never change state by themselves.
- Persistent `PromptStore` gives monotonic sequence numbers across restarts and rejects
  prompt replay (`ReplayRejected`); other-session origins are rejected at the state layer
  and stale/cross-session declarations at the bridge layer.

## Status on the WorkBuddy host

- Receipt path and user-origin derivation are unit-tested (46 tests green) and exercised
  on real captures in `evidence/full-delivery-controller/2026-09-02/` and
  `evidence/auto-blackbox/run-20260902T170022Z/`.
- Real host firing is verified by the automatic black-box run: official project-scoped
  command hooks (`<project>/.codebuddy/settings.local.json`) executed the bridge for real
  WorkBuddy CLI sessions — UserPromptSubmit/PostToolUse/Stop events entered the formal
  Core v3.0.6 (23/23 assertions PASS; see `evidence/auto-blackbox/README.md`).
  `hooks/hooks.json` stays inert by design; nothing is registered globally and WorkBuddy
  global settings are unmodified.
