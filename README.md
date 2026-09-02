# enterprise-ai-project-delivery-workbuddy-adapter

WorkBuddy-specific integration candidate for the [enterprise-ai-project-delivery Core](https://github.com/tl3981390-blip/enterprise-ai-project-delivery). This repository contains no fork or copy of the Delivery Core, its Runtime, Evidence model, Human Authority or MODULE code.

## Current truth

**`CONTROLLER_NOT_CONNECTED`** for full Human Authority control.

A real local audit (see `docs/AUDIT_WORKBUDDY_HOOKS.md`) proves, from this machine's
bundled engine and official docs, that WorkBuddy Hook input exposes
`session_id / transcript_path / cwd / permission_mode / hook_event_name` plus
event-specific fields, with **no** `event_id`, and **no** trusted `conversation_id` /
`message_id`. There are no distinct host events for user pause / resume / cancel /
correction / plan approval / requirement change. Those operations therefore remain
fail-closed, and a Hook event id is never a user message identity.

The safe, project-scoped subset IS implemented on branch `workbuddy-controller-bridge`:

| Area | Behavior |
| --- | --- |
| Project gate | Active only when `<project>/.workbuddy/delivery-contract.json` equals exactly `{"adapter": "enterprise-ai-project-delivery-workbuddy-adapter", "enabled": true}`. Everything else stays fully inert (no state, no session, no Stop interception). |
| Bridge State | `<project>/.workbuddy/bridge/STATE.json` + `AUDIT.jsonl`; session bind/resume/end; per-episode receipts; replay protection (bounded digest window + duplicate rejection). |
| Tool Evidence | Receipts are created only from genuine `PostToolUse` input carrying a real `tool_response`. Model-claimed PASS can never become evidence. |
| Stop / Evidence Gate | Runs only when the project is enabled AND a legal controller session exists. No evidence / insufficient evidence -> completion blocked (`continue:false`). |
| Human Authority | USER_PAUSE / USER_RESUME / USER_CANCEL / USER_CORRECTION / PLAN_APPROVAL / REQUIREMENT_CHANGE all fail-closed; text such as "暂停/取消" changes nothing. |

See `docs/CONTROLLER_CONFORMANCE.md` and `docs/REGISTRATION.md`.

## Core compatibility (read-only target, never vendored)

| Field | Value |
| --- | --- |
| Core version | `3.0.6` |
| Tag | `v3.0.6` |
| Commit | `0937642afa0d488b20701c87e2ee3cd2a921cd2d` |
| Asset SHA-256 | `2512a954e1a73e3a6070318d7018ac6424d6904164db19e560f8ba9ec0cd4d5f` |

## Probing

`python src/probe_workbuddy.py --workbuddy-home <path>` is read-only. For full local
evidence it accepts `--engine-source <cli/dist/codebuddy.js>` and
`--hooks-doc <.../docs/cn/cli/hooks.md>`.

## Tests

```bash
python -m pytest tests/
```

Coverage: 36 tests, including the 11 required acceptance points (lazy un-enabled
projects; state create/resume; receipts only from real tool responses; Stop blocked
without evidence; Stop blocked with insufficient evidence; duplicate hook events
rejected; event_id not a message_id; user text not changing runtime state; all Human
Authority transitions fail-closed without host identity; bridge independent of the
author's machine paths; bridge never modifies Core files).

## Development status

Adapter-development repository, not a released WorkBuddy product. Remains
`PENDING_EXTERNAL_VALIDATION` / `BLOCKED_BY_WORKBUDDY_CAPABILITY` for anything that
requires a live desktop registration run; must not be reported `CONTROLLER_CONNECTED`
until every conformance check passes in a real WorkBuddy session.
