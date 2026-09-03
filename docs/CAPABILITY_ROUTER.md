# Harness Capability Router (workbuddy-full-delivery-controller)

## The only legal candidate source

The Router consumes a **Harness Skill Snapshot** with
`source = "harness_available_skills"` and Bridge-written PostToolUse provenance
(`hook_event_name`, `tool_name`, `tool_use_id`, `output_sha256`). The list must
be carried by the Host receipt itself; model-transcribed context is not machine
evidence and is rejected.

Anything else is rejected by code (`harness_skill_snapshot.SnapshotRejected`):

- local workspace / drive scans;
- `.workbuddy/skills` disk walks;
- hand-written mock registries;
- fixed skill names / pre-baked candidate lists;
- model guesses about "what the harness probably has".

## Eligibility chain (machine reasons)

For each real candidate the Router applies, in order:

1. `not_available_in_current_session`
2. `identity_incomplete` (missing name or description)
3. `permission_denied` / `permission_unknown`
4. `task_mismatch_no_text_overlap` — lexical overlap between the real Work Unit text and the
   candidate identity+description as exposed by the Harness (CJK bigrams + ascii words;
   generic function words are stripped from the query). No skill name is hardcoded anywhere.

## Decision

`route(snapshot, work_unit_text)` returns a `RouterDecision`:

- `decision` = winning skill identity **or** `NO_ELIGIBLE_HARNESS_SKILL`;
- `reason` explains the minimal-sufficient, deterministic choice;
- `exclusions` carries one machine reason per excluded candidate;
- `ranked` lists every eligible candidate with its overlap score.

Selection is a *decision artifact only*. Invocation is a separate, real WorkBuddy step
(`Skill` tool load + execution) whose results become HARNESS_EXECUTION receipts via
`harness_receipts.receipt_from_posttooluse`.

## Current validation boundary

Earlier snapshots are historical only and do not satisfy the provenance rule. In
the currently tested WorkBuddy CLI, the discovery receipt reports merely that
`/skills` ran; it does not carry a list. The correct status is
`PENDING_EXTERNAL_VALIDATION`, not an automatic-selection PASS.
