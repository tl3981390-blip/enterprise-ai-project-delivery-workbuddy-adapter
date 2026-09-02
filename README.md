# enterprise-ai-project-delivery-workbuddy-adapter

WorkBuddy-specific integration candidate for the [enterprise-ai-project-delivery Core](https://github.com/tl3981390-blip/enterprise-ai-project-delivery). This repository contains no fork or copy of the Delivery Core.

## Current truth

`CONTROLLER_NOT_CONNECTED` for WorkBuddy full Human Authority control.

WorkBuddy hooks can support project-scoped lifecycle observation, tool-result capture, a persisted bridge state, a Stop/Evidence gate and replay detection. The currently observed Hook contract does not expose a trusted `conversation_id` and `message_id` for user pause, resume, cancel, correction, plan approval or requirement change. Those operations therefore remain fail-closed. A Hook event id may be used for technical replay detection only; it is never treated as user authority.

Do not enable the candidate hooks globally. They are deliberately inert unless a project explicitly opts in, and this repository must not be released as a connected Controller until the conformance probe proves the required host fields and lifecycle events.

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

This is an adapter-development repository, not a released WorkBuddy product. It must remain `PENDING_EXTERNAL_VALIDATION` until a real WorkBuddy run proves all controller conformance checks.
