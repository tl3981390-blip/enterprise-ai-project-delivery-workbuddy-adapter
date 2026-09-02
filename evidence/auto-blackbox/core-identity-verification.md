# Formal Core identity verification evidence

Target: the ONLY Core used by this adapter —

| field | expected | verified where |
| --- | --- | --- |
| skill | `enterprise-ai-project-delivery` | `~/.workbuddy/skills/enterprise-ai-project-delivery` installed (SELF_CONTAINED_FULL_CORE) |
| version | `3.0.6` | `SKILL.md` frontmatter; `INSTALL_INFO.json`; `共享/schema/RELEASE_METADATA.json`; `harness_manifest.json` |
| tag | `v3.0.6` | `INSTALL_INFO.json` `canonical_identity`; `RELEASE_METADATA.json` `tag` |
| commit | `0937642afa0d488b20701c87e2ee3cd2a921cd2d` | `INSTALL_INFO.json` `canonical_identity`; `hooks/bridge/bridge_config.json` `core_identity.commit`; README |
| asset sha256 | `2512a954e1a73e3a6070318d7018ac6424d6904164db19e560f8ba9ec0cd4d5f` | `hooks/bridge/bridge_config.json` `core_identity.asset_sha256`; README |

The runtime actually exercised is the installed `共享/scripts/*` (delivery_runtime,
harness_adapter_core, evidence_core, understanding_core) — read-only imported by
`hooks/bridge/wbbridge.py`; no Core file is modified.  `INSTALL_INFO.json` records
`"mode": "SELF_CONTAINED_FULL_CORE"` and `"release_asset_identity_preserved": true`.

## Online re-resolution attempts (2026-09-02, all recorded, no fabrication)

GitHub (github.com) was intermittently unreachable from this machine during the
session.  Attempts and outcomes:

- `git ls-remote https://github.com/tl3981390-blip/enterprise-ai-project-delivery refs/tags/v3.0.6^{}` — connection reset / timeouts on multiple tries (~23:59 UTC, ~02:0x local retries).
- `curl -L https://github.com/.../releases/download/v3.0.6/enterprise-ai-project-delivery-v3.0.6.zip` — curl rc=56/28, no asset downloaded (temp dir `%TEMP%\wbfdc-core-verify` empty).
- The adapter origin `git fetch origin` succeeded earlier in the session (network is intermittent), so the failures are transient connectivity, not an invalid reference.

→ Because the GitHub objects could not be fetched at run time, the commit hash and
asset SHA could not be independently re-derived online; they are verified as
*consistently recorded* in the installed metadata above and in the Adapter config.
This is the documented limitation; the offline-verifiable identity triple is
machine-readable in `hooks/bridge/bridge_config.json`.
