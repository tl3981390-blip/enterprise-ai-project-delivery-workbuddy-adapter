"""WorkBuddy host-event bridge library (part of the Adapter branch, NOT the Core).

Purpose
-------
Turn REAL WorkBuddy host hook events (UserPromptSubmit / PostToolUse / Stop) into
signed Core-runtime events for the officially installed enterprise-ai-project-delivery
v3.0.6 (see INSTALL_INFO + RELEASE_METADATA identity in bridge_config).  This module
never copies or modifies Core files: it only imports the installed Core scripts.

Identity mapping (documented, auditable)
----------------------------------------
- WorkBuddy organises one transcript per host session; the host ``session_id`` is
  therefore reused as the Adapter ``conversation_id`` (one host session == one
  conversation).  Every event records this mapping in the audit log.
- UserPromptSubmit ``event_id`` is the model-unforgeable ``adapter_message_id``
  produced by ``human_authority.originate_user_prompt`` from the REAL payload
  (session_id + seq + prompt hash).  Replays and other sessions are rejected.
- PostToolUse ``event_id`` is the host ``generation_id``/``call_id`` (unique per run).
- Stop ``event_id`` is a session-scoped ``stop-<n>`` id.

Audit
-----
Every real host event is appended (raw + mapped) to ``audit/<host_session>.jsonl``
under the project bridge state directory, so the black-box trace is independently
verifiable without touching WorkBuddy global settings.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Locate the formally installed Core (read-only reference; never modified).
# --------------------------------------------------------------------------
BRIDGE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BRIDGE_DIR / "bridge_config.json"


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(f"bridge_config.json missing: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def ensure_core_scripts(config: dict) -> None:
    core_scripts = config["core_scripts"]
    if not Path(core_scripts).joinpath("harness_adapter_core.py").is_file():
        raise FileNotFoundError(f"formal Core runtime not found at {core_scripts}")
    if core_scripts not in sys.path:
        sys.path.insert(0, core_scripts)


def host_session_id(payload: dict) -> str:
    sid = str(payload.get("session_id") or "").strip()
    if not sid:
        raise ValueError("host payload missing session_id")
    return sid


def project_root() -> Path:
    """The project directory is the hook process cwd (host sets it to the project).

    CODEBUDDY_PROJECT_DIR may arrive in POSIX form (``/c/...``) under Git Bash and
    would confuse Windows ``pathlib``, so the real process cwd is authoritative.
    """
    cwd = Path.cwd().resolve()
    return cwd


def bridge_state_dir(payload: dict) -> Path:
    cfg = load_config()
    root = project_root()
    state_dir = root / cfg.get("state_rel_dir", ".codebuddy/bridge/state")
    return state_dir


def audit_dir(payload: dict) -> Path:
    return bridge_state_dir(payload) / "audit"


def append_audit(payload: dict, kind: str, outcome: dict) -> str:
    sid = host_session_id(payload)
    ad = audit_dir(payload)
    ad.mkdir(parents=True, exist_ok=True)
    record = {
        "kind": kind,
        "host_session_id": sid,
        "conversation_id": sid,  # documented WorkBuddy mapping (one session == one conversation)
        "at": datetime.now(timezone.utc).isoformat(),
        "host_payload": payload,
        "outcome": outcome,
    }
    target = ad / f"{sid}.jsonl"
    with target.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return str(target)


def load_harness_modules(config: dict):
    """Import the official Core bridge classes inside the hook process."""
    ensure_core_scripts(config)
    from harness_adapter_core import HarnessAdapterController  # noqa: PLC0415
    return HarnessAdapterController


def make_controller(payload: dict, config: dict):
    HarnessAdapterController = load_harness_modules(config)
    sid = host_session_id(payload)
    state_file = bridge_state_dir(payload) / "delivery" / f"{sid}.json"
    return HarnessAdapterController(
        harness=config["harness"],
        state_path=state_file,
        transport_secret=config["transport_secret"])


def event_for(payload: dict, event_type: str, event_id: str) -> dict:
    """Build the event dict; transport signature is added by Core's caller helpers."""
    sid = host_session_id(payload)
    # Keep only the real host fields; never invent user authority here.
    return {
        "harness": load_config()["harness"],
        "session_id": sid,
        "conversation_id": sid,
        "event_id": event_id,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": f"WORKBUDDY_HOST:{payload.get('hook_event_name', event_type)}",
        "payload": payload,
    }


def read_stdin_payload() -> dict:
    """Read the host JSON payload robustly across Windows codepages.

    The host writes UTF-8 JSON; on zh-CN Windows Python may default to the
    locale codepage and insert surrogate escapes.  Decoding the raw bytes as
    UTF-8 with ``replace`` guarantees a clean string for ``json.loads``.
    """
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        raise ValueError("hook invoked with empty stdin")
    text = raw.decode("utf-8", errors="replace")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("hook stdin is not a JSON object")
    return data


def always_exit_zero(func):
    """Host contract: a hook must never crash the host runtime."""
    def _wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            # ASCII-safe output: host console may be a non-UTF-8 codepage.
            print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        except Exception as exc:  # noqa: BLE001
            try:
                msg = f"[workbuddy-bridge] {type(exc).__name__}: {exc}"
                print(json.dumps({"continue": True,
                                  "systemMessage": msg.encode("utf-8", "replace").decode("utf-8")},
                                 ensure_ascii=True))
            except Exception:  # noqa: BLE001
                print('{"continue": true, "systemMessage": "[workbuddy-bridge] hook error"}')
        finally:
            sys.exit(0)
    return _wrapper
