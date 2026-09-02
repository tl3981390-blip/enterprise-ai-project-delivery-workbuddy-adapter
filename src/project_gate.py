"""Project-level activation gate (requirement A).

A project is served by the bridge only when the exact opt-in file exists at the project
root:

    <project>/.workbuddy/delivery-contract.json
    {"adapter": "enterprise-ai-project-delivery-workbuddy-adapter", "enabled": true}

Any other state - missing file, malformed JSON, different adapter id, disabled flag -
keeps every hook entry point completely inert: no Controller Session, no state files,
no Stop interception, no side effects on ordinary WorkBuddy conversations.

Root resolution deliberately trusts only host-provided context:
  1. CODEBUDDY_PROJECT_DIR (documented as the project root directory)
  2. the hook payload `cwd`
Nothing is guessed from transcripts or from this machine's layout.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from controller_contract import ADAPTER_ID, project_enabled

CONTRACT_RELATIVE_PATH = Path(".workbuddy") / "delivery-contract.json"


def read_contract(project_root: Path) -> Optional[dict[str, Any]]:
    """Read the opt-in contract. Missing or malformed files yield None (never raise)."""
    try:
        raw = (Path(project_root) / CONTRACT_RELATIVE_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def enabled_at(project_root: Path) -> bool:
    """True only for the exact opt-in contract content."""
    contract = read_contract(project_root)
    return contract is not None and project_enabled(contract)


def candidate_roots(payload: dict[str, Any], env: Optional[dict[str, str]] = None) -> list[Path]:
    """Host-provided candidates for the project root, most trusted first."""
    env = os.environ if env is None else env
    candidates: list[Path] = []
    env_dir = env.get("CODEBUDDY_PROJECT_DIR")
    if env_dir and str(env_dir).strip():
        candidates.append(Path(env_dir).expanduser())
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        candidates.append(Path(cwd).expanduser())
    return candidates


def locate_enabled_root(payload: dict[str, Any],
                        env: Optional[dict[str, str]] = None) -> Optional[Path]:
    """Return the project root whose contract is exactly enabled, else None.

    None keeps the caller fully inert: it is not an error and must not create anything.
    """
    seen: set[str] = set()
    for root in candidate_roots(payload, env):
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        try:
            if enabled_at(root):
                return Path(root)
        except OSError:
            continue
    return None
