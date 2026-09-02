"""Human Authority Controller for WorkBuddy.

The only legal User Origin is a REAL UserPromptSubmit hook payload:

    payload.origin == "UserPromptSubmit" and a host-provided session_id and prompt text

The adapter derives a persistent, auditable, model-unforgeable ``adapter_message_id``:

    adapter_message_id = am-<sha256(session_id|seq|prompt_hash)[:32]>-<seq>

Model text, tool output, Stop events and PostToolUse events can NEVER produce an
adapter_message_id. Only explicit, unambiguous user control commands change state:

    "暂停交付"   -> PAUSE
    "继续交付"   -> RESUME
    "取消交付"   -> CANCEL
    "记录纠正：<…>" -> CORRECTION(text)

Everything else (questions, vague phrasing, model restatements, inferred intent)
is not a control and cannot move the state machine. Replay of the same prompt hash
in the same session is rejected; other sessions are rejected; stale plan revisions
are rejected at the caller level.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

USER_ORIGIN = "UserPromptSubmit"

CONTROL_PHRASES = {
    "暂停交付": "PAUSE",
    "继续交付": "RESUME",
    "取消交付": "CANCEL",
}
CORRECTION_PREFIX = "记录纠正："


class NotUserOrigin(Exception):
    """This payload did not come from a real UserPromptSubmit hook."""


class ReplayRejected(Exception):
    """Same canonical prompt already consumed in this session."""


class ControlRejected(Exception):
    """Not an explicit, unambiguous user control instruction."""


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def classify_control(prompt: str) -> tuple[str, str | None] | None:
    """Return (KIND, payload) for explicit user controls; None otherwise."""
    text = prompt.strip()
    if text in CONTROL_PHRASES:
        return CONTROL_PHRASES[text], None
    if text.startswith(CORRECTION_PREFIX):
        body = text[len(CORRECTION_PREFIX):].strip()
        if not body:
            raise ControlRejected("correction requires content after '记录纠正：'")
        return "CORRECTION", body
    return None


def canonical_prompt_hash(prompt: str) -> str:
    return _sha256(prompt.strip().encode("utf-8"))


@dataclass(frozen=True)
class AdapterUserOrigin:
    adapter_message_id: str
    session_id: str
    seq: int
    prompt_hash: str
    kind: str | None          # PAUSE/RESUME/CANCEL/CORRECTION or None for plain prompts
    payload: str | None       # CORRECTION body or None
    created_at: str

    def as_json(self) -> dict[str, Any]:
        return {
            "adapter_message_id": self.adapter_message_id,
            "session_id": self.session_id,
            "seq": self.seq,
            "prompt_hash": self.prompt_hash,
            "kind": self.kind,
            "payload": self.payload,
            "created_at": self.created_at,
            "origin": USER_ORIGIN,
            "source": "harness_asserted_user_origin",
        }


class PromptStore:
    """Persistent per-session monotonic counter + replay guard (survives restart)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def next(self, session_id: str, prompt_hash: str) -> tuple[int, bool]:
        """Return (seq, is_new). is_new=False means a replay of an already-used prompt."""
        data = self._load()
        entry = data.get(session_id, {"seq": 0, "used": []})
        if prompt_hash in entry["used"]:
            return entry["seq"], False
        entry["seq"] += 1
        entry["used"].append(prompt_hash)
        data[session_id] = entry
        self._save(data)
        return entry["seq"], True

    def forget(self, session_id: str, prompt_hash: str) -> None:
        """Remove one recorded prompt so a FAILED real control can be retried.

        Only the bridge calls this right after Core rejected a genuine user
        control (e.g. stale state machine).  It never creates authority; it only
        makes an already-real failed instruction retryable after recovery.
        """
        data = self._load()
        entry = data.get(session_id, {"seq": 0, "used": []})
        if prompt_hash in entry["used"]:
            entry["used"] = [h for h in entry["used"] if h != prompt_hash]
            entry["seq"] = max(entry["seq"] - 1, 0)
            data[session_id] = entry
            self._save(data)


def originate_user_prompt(payload: dict[str, Any], store: PromptStore) -> AdapterUserOrigin:
    """The ONLY factory for a Harness-asserted User Origin.

    Payload must be a genuine UserPromptSubmit record: host origin tag, host
    session_id, raw user prompt. Anything else raises NotUserOrigin.
    """
    if payload.get("origin") != USER_ORIGIN:
        raise NotUserOrigin(
            f"only {USER_ORIGIN} can assert user origin; got {payload.get('origin')!r}")
    session_id = str(payload.get("session_id") or "").strip()
    prompt = str(payload.get("prompt") or "").strip()
    if not session_id or not prompt:
        raise NotUserOrigin("UserPromptSubmit payload missing session_id or prompt")
    p_hash = canonical_prompt_hash(prompt)
    seq, is_new = store.next(session_id, p_hash)
    if not is_new:
        raise ReplayRejected(f"replayed prompt in session {session_id}: {p_hash[:12]}…")
    mid = "am-" + _sha256(f"{session_id}|{seq}|{p_hash}".encode("utf-8"))[:32] + f"-{seq}"
    control = classify_control(prompt)
    kind, ctrl_payload = control if control else (None, None)
    return AdapterUserOrigin(
        adapter_message_id=mid,
        session_id=session_id,
        seq=seq,
        prompt_hash=p_hash,
        kind=kind,
        payload=ctrl_payload,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )


CONTROL_STATES = {"RUNNING", "PAUSED", "CANCELLED", "COMPLETED"}


@dataclass
class HumanAuthorityState:
    session_id: str
    state: str = "RUNNING"
    plan_revision: int = 1
    corrections: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.corrections is None:
            self.corrections = []

    def apply(self, origin: AdapterUserOrigin, plan_revision: int | None = None) -> str:
        """Apply a USER-asserted control. Model-origin calls can never reach here."""
        if origin.session_id != self.session_id:
            raise ControlRejected("other-session user origin rejected")
        if origin.kind is None:
            return self.state  # ordinary user prompt: no state change
        if origin.kind == "PAUSE":
            if self.state != "CANCELLED" and self.state != "COMPLETED":
                self.state = "PAUSED"
        elif origin.kind == "RESUME":
            if self.state == "PAUSED":
                self.state = "RUNNING"
        elif origin.kind == "CANCEL":
            self.state = "CANCELLED"
        elif origin.kind == "CORRECTION":
            if self.state == "CANCELLED" or self.state == "COMPLETED":
                raise ControlRejected("correction on terminal state rejected")
            self.corrections.append(origin.payload or "")
            if plan_revision is not None and plan_revision > self.plan_revision:
                self.plan_revision = plan_revision
        return self.state
