# WorkBuddy Host-Event Bridge — real wiring (workbuddy-full-delivery-controller)

## Mechanism findings (verified on host 5.5.1, this session)

1. The WorkBuddy host executes **project-scoped command hooks** declared in
   `<project>/.codebuddy/settings.local.json` for the events `UserPromptSubmit`,
   `PostToolUse` and `Stop`.  A probe hook was fired by the real host and captured
   a genuine payload (session_id, tool_use_id, generation_id, model) — see
   `evidence/full-delivery-controller/2026-09-02/real-session/` and the demo
   project audit file `.codebuddy/bridge/state/audit/<host-session>.jsonl`.
2. The **hookify** plugin is *present in the official marketplace* but is **not
   enabled** (`enabledPlugins` has no hookify entry), and its rule engine only
   supports `warn`/`block` semantics — it cannot execute a Python bridge.  The
   Adapter therefore binds the real bridge to the host's native command-hook
   interface (the officially installed plugin/hook contract), which is the
   mechanism that demonstrably fires.
3. Windows stdin is delivered as UTF-8; Python must read `stdin.buffer` and
   decode explicitly, otherwise locale codepage surrogate errors break parsing.

## Bridge files (all in this Adapter branch; none of the Core is modified)

- `hooks/bridge/wbbridge.py` — shared plumbing: Core-runtime discovery (formal
  installed v3.0.6), host-session audit trail, path resolution, signed event
  construction, stdin/ASCII-safe output helpers.
- `hooks/bridge/bridge.py` — dispatch entry points:
  - `userpromptsubmit`  -> Human Authority (verbatim capture only; intent is the model's job)
  - `posttooluse`       -> registered work-unit receipts -> Core evidence ledger
  - `stop`              -> Core completion gate (observe by default; enforce opt-in)
  - `bootstrap`         -> create the delivery session from the real project goal
- `hooks/bridge/bridge_config.json` — Adapter config referencing the formal Core
  (v3.0.6, commit 0937642afa0d488b20701c87e2ee3cd2a921cd2d,
  asset sha256 2512a954e1a73e3a6070318d7018ac6424d6904164db19e560f8ba9ec0cd4d5f).

## Real acceptance evidence recorded in this session

- Real `PostToolUse` host events fired the bridge (audit shows tool=Bash/Edit/Write
  entries with real call_id/generation_id).  Two matching work units produced Core
  receipts recorded in the delivery session's Canonical Evidence Ledger:
  - `workbuddy:ptu-call_00_fkLPW…` (REAL_HOST_EVENT_BRIDGE) — PASS
  - `workbuddy:ptu-call_00_ET_9j1o…` (CANONICAL_EVIDENCE_LEDGER) — PASS
- Historical capability-selection artifacts are retained as historical records,
  not proof: they lacked Bridge-attested Host list provenance.

## Honest status

Real host events are the only PASS source. Earlier automatic black-box records
verified Hook firing and Core receipts, but cannot verify automatic Skill
selection under the current provenance rule. The current Host returns no skill
list in the discovery receipt, so that product gate is
`PENDING_EXTERNAL_VALIDATION`.
