"""Project-scoped bridge state (requirement B).

Persistence lives only under an enabled project:

    <project>/.workbuddy/bridge/STATE.json   - single source of truth for this bridge
    <project>/.workbuddy/bridge/AUDIT.jsonl  - append-only audit trail

Nothing is ever written for a project that is not explicitly enabled, and nothing is
written outside the resolved project root.  State files never embed this machine's
layout: project_root is stored only so a state file can be re-anchored if a checkout
moves; all writes go strictly under the root that was resolved from host context.

Session binding, replay protection and auditing semantics:

* bind_session   - first sighting of a session id creates a controller session episode;
                   repeated sightings of an active session resume it idempotently;
                   a closed session id opens a fresh episode (old receipts are not reused).
* end_session    - closes the active episode; used by SessionEnd (reason clear/logout/
                   prompt_input_exit/other).
* replay guard   - the verified host payload has NO event_id, so replay protection is a
                   best-effort bounded digest window scoped to (session_id + canonical
                   payload signature).  It only ever drops a duplicate, never creates one.

The module is stdlib-only and deliberately has no knowledge of the Delivery Core.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1
BRIDGE_DIR_NAME = "bridge"
STATE_FILE_NAME = "STATE.json"
AUDIT_FILE_NAME = "AUDIT.jsonl"
REPLAY_WINDOW_SECONDS = 30
MAX_RECEIPTS_PER_EPISODE = 300


class BridgeStateError(Exception):
    """Raised when state exists but cannot be trusted (corrupt / schema drift)."""


def bridge_dir(project_root: Path) -> Path:
    return Path(project_root) / ".workbuddy" / BRIDGE_DIR_NAME


def state_file(project_root: Path) -> Path:
    return bridge_dir(project_root) / STATE_FILE_NAME


def audit_file(project_root: Path) -> Path:
    return bridge_dir(project_root) / AUDIT_FILE_NAME


def canonical_signature(parts: dict[str, Any]) -> str:
    """Deterministic digest of host payload facts for replay protection."""
    def _default(value: Any) -> Any:
        return str(value)

    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=_default)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def new_bridge_id() -> str:
    return str(uuid.uuid4())


def empty_state(project_root: Path, ts: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "bridge_id": new_bridge_id(),
        "project_root": str(Path(project_root)),
        "created_at": ts,
        "updated_at": ts,
        "sessions": {},
        "replay": {"window_seconds": REPLAY_WINDOW_SECONDS, "seen": {}},
    }


def load_state(project_root: Path) -> Optional[dict[str, Any]]:
    """Return the persisted state or None when no state exists yet.

    Corrupt or schema-drifted state raises BridgeStateError instead of being silently
    overwritten: fail-closed beats data loss.
    """
    path = state_file(project_root)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise BridgeStateError(f"corrupt state file {path}: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        raise BridgeStateError(f"unexpected state schema at {path}")
    return state


def save_state(project_root: Path, state: dict[str, Any], ts: str) -> None:
    """Atomically persist state strictly under the given project root."""
    state["updated_at"] = ts
    target = state_file(project_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{STATE_FILE_NAME}.tmp.{uuid.uuid4().hex}")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, target)


def append_audit(project_root: Path, entry: dict[str, Any], ts: str) -> None:
    """Append one audit line. Entry is enriched with a timestamp and never edited later."""
    record = {"ts": ts, **entry}
    path = audit_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Session binding
# ---------------------------------------------------------------------------

def _new_session_entry(session_id: str, source: str, transcript_path: str, ts: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "status": "active",
        "episode": 1,
        "episode_started_at": ts,
        "first_seen_at": ts,
        "last_seen_at": ts,
        "source": source,
        "transcript_path": transcript_path or "",
        "receipts": [],
        "closed_at": None,
        "closed_reason": None,
    }


def bind_session(state: dict[str, Any], session_id: str, source: str,
                 transcript_path: str, ts: str) -> str:
    """Bind/refresh a controller session. Returns the action taken."""
    sessions: dict[str, Any] = state.setdefault("sessions", {})
    existing = sessions.get(session_id)
    if existing is None:
        sessions[session_id] = _new_session_entry(session_id, source, transcript_path, ts)
        return "created"
    if existing.get("status") == "active":
        existing["last_seen_at"] = ts
        existing["source"] = source
        if transcript_path:
            existing["transcript_path"] = transcript_path
        return "resumed"
    # Closed episode -> a fresh episode for the same session id.
    existing["episode"] = int(existing.get("episode", 1)) + 1
    existing["status"] = "active"
    existing["episode_started_at"] = ts
    existing["last_seen_at"] = ts
    existing["source"] = source
    existing["closed_at"] = None
    existing["closed_reason"] = None
    existing["receipts"] = []
    return "reopened"


def end_session(state: dict[str, Any], session_id: str, reason: str, ts: str) -> str:
    sessions: dict[str, Any] = state.get("sessions", {})
    entry = sessions.get(session_id)
    if entry is None or entry.get("status") != "active":
        return "ignored"
    entry["status"] = "closed"
    entry["closed_at"] = ts
    entry["closed_reason"] = reason or "other"
    return "closed"


def active_session(state: dict[str, Any], session_id: str) -> Optional[dict[str, Any]]:
    entry = state.get("sessions", {}).get(session_id)
    if entry is None or entry.get("status") != "active":
        return None
    return entry


def has_active_session(state: dict[str, Any], session_id: str) -> bool:
    return active_session(state, session_id) is not None


# ---------------------------------------------------------------------------
# Replay protection (host provides no event_id - verified on this machine)
# ---------------------------------------------------------------------------

def _replay_parts(payload_signature: str, session_id: str) -> dict[str, Any]:
    return {"scope": "replay", "session_id": session_id, "signature": payload_signature}


def is_replay(state: dict[str, Any], payload_signature: str, session_id: str,
              ts: str, window_seconds: Optional[int] = None) -> bool:
    replay = state.setdefault("replay", {})
    window = window_seconds if window_seconds is not None else int(
        replay.get("window_seconds", REPLAY_WINDOW_SECONDS))
    sig = canonical_signature(_replay_parts(payload_signature, session_id))
    seen: dict[str, str] = replay.setdefault("seen", {})
    try:
        earlier = seen.get(sig)
    except TypeError:  # pragma: no cover - defensive
        earlier = None
    if earlier is None:
        seen[sig] = ts
        return False
    # Same signature seen before; only counts as a replay inside the bounded window.
    if _within_window(earlier, ts, window):
        return True
    seen[sig] = ts  # expired -> re-arm
    return False


def _within_window(earlier_ts: str, ts: str, window_seconds: int) -> bool:
    try:
        from datetime import datetime
        fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
        earlier = datetime.strptime(earlier_ts, fmt)
        current = datetime.strptime(ts, fmt)
        return (current - earlier).total_seconds() <= window_seconds
    except (ValueError, TypeError):  # pragma: no cover - non-timestamp ts in tests
        return False


def prune_replay(state: dict[str, Any], ts: str,
                 window_seconds: Optional[int] = None) -> None:
    replay = state.get("replay", {})
    window = window_seconds if window_seconds is not None else int(
        replay.get("window_seconds", REPLAY_WINDOW_SECONDS))
    seen: dict[str, str] = replay.get("seen", {})
    stale = [sig for sig, seen_ts in seen.items() if not _within_window(seen_ts, ts, window)]
    for sig in stale:
        seen.pop(sig, None)


# ---------------------------------------------------------------------------
# Receipts (evidence candidates, counted per active episode)
# ---------------------------------------------------------------------------

def add_receipt(state: dict[str, Any], session_id: str, receipt: dict[str, Any]) -> str:
    entry = state.get("sessions", {}).get(session_id)
    if entry is None or entry.get("status") != "active":
        return "no_session"
    receipts: list[dict[str, Any]] = entry.setdefault("receipts", [])
    for existing in receipts:
        if existing.get("digest") == receipt.get("digest"):
            return "duplicate"
    receipts.append(receipt)
    if len(receipts) > MAX_RECEIPTS_PER_EPISODE:  # bounded memory, oldest dropped
        del receipts[: len(receipts) - MAX_RECEIPTS_PER_EPISODE]
    return "recorded"


def session_receipts(state: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    entry = state.get("sessions", {}).get(session_id)
    if entry is None:
        return []
    return list(entry.get("receipts", []))
