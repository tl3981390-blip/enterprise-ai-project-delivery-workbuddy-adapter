# Harness Capability Router (workbuddy-full-delivery-controller)

## The only legal candidate source

The Router consumes a **Harness Skill Snapshot** that must declare
`source = "skill_tool_available_skills"` (or `harness_available_skills`). That snapshot is
the current WorkBuddy/Harness session's own Skill-tool / available_skills surface —
transcribed as raw machine data, never invented.

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
3. `not_verified_callable_in_this_session` — verified only via a REAL Skill-tool load/invocation record
4. `permission_denied` / `permission_unknown`
5. `task_mismatch_no_text_overlap` — lexical overlap between the real Work Unit text and the
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

## Real end-to-end run (evidence/2026-09-02)

- `harness-skill-snapshot.real.json` — current-session snapshot; only
  `enterprise-ai-project-delivery` and `git-state-change-regression` carry
  `verified_callable: true` because both were REALLY loaded via the Skill tool this session.
- `router.decision.wu-git.json` — for the Work Unit "对当前改动执行 Git 状态安全检查…",
  the Router returned `decision = git-state-change-regression` (real code run).
- The selected skill was really loaded and its protocol executed in the isolated demo
  (`git-state-report.json`): pre/post porcelain, head diff limited to the intended file,
  zero cache pollution, full pytest green, working tree clean.
