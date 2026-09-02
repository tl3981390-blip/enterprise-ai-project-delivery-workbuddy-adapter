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
- Control commands are exact-match only: 暂停交付 / 继续交付 / 取消交付 / `记录纠正：…`.
  Vague phrasing and inferred intent never change state.
- Persistent `PromptStore` gives monotonic sequence numbers across restarts and rejects
  prompt replay (`ReplayRejected`); other-session origins are rejected at the state layer.

## Status on the WorkBuddy host

- Receipt path and user-origin derivation are **unit-tested (34 tests green) and exercised
  on real captured outputs** in `evidence/2026-09-02/evidence-ledger.json` +
  `scope-audit.jsonl`.
- Live host firing of `UserPromptSubmit` / `PostToolUse` cannot be triggered from inside a
  session; the hooks file is a **candidate, inert by default** and nothing is registered
  globally or in WorkBuddy settings. Live hook conformance remains
  `PENDING_EXTERNAL_VALIDATION` until a real host run supplies hook payloads.
