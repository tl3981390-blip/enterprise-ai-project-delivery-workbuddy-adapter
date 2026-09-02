"""Human Authority Controller for WorkBuddy.

Division of labour (deliberate):

* The ADAPTER (this module + the bridge hooks) never guesses what a user meant.
  Natural-language intent recognition is the MODEL's job, in the conversation.
* The adapter's job is to GOVERN the model:
  1. Record every REAL UserPromptSubmit hook payload verbatim (session_id,
     prompt text, canonical hash) as an immutable ``AdapterUserOrigin``.  Only
     ``origin == "UserPromptSubmit"`` from the real host may create one.
  2. Derive a persistent, auditable, model-unforgeable ``adapter_message_id``
     from that real payload:
         adapter_message_id = am-<sha256(session_id|seq|prompt_hash)[:32]>-<seq>
     Model text, tool output, Stop events and PostToolUse events can NEVER
     produce an adapter_message_id.
  3. When the model decides — from a REAL user message it can point to — that
     the user is pausing, resuming, cancelling or correcting the delivery, the
     model must call ``declare_control(origin, kind, ...)``.  The declaration is
     recorded WITH the verbatim user text it is based on, so any misjudgement
     is visible and correctable by the user.  There is no phrase table here:
     the adapter does not interpret "停停停" or "继续交付"; the model does.

State machine (Core side) enforces: exact control kinds only
(PAUSE/RESUME/CANCEL/CORRECTION), replay of the same prompt hash in the same
session is rejected, other sessions are rejected, stale plan revisions are
rejected.  Ambiguous or ordinary user messages never move the state by
themselves — they only create an origin the model may or may not act on.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

USER_ORIGIN = "UserPromptSubmit"
MODEL_DECLARED = "MODEL_INTERPRETATION_OF_REAL_USER_PROMPT"

CONTROL_KINDS = ("PAUSE", "RESUME", "CANCEL", "CORRECTION")


class NotUserOrigin(Exception):
    """This payload did not come from a real UserPromptSubmit hook."""


class ReplayRejected(Exception):
    """Same canonical prompt already consumed in this session."""


class ControlRejected(Exception):
    """The declared control is invalid, ambiguous or illegal for this state."""


class ControlNotDeclared(Exception):
    """A real user origin exists but the model never declared a control kind."""


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def canonical_prompt_hash(prompt: str) -> str:
    return _sha256(prompt.strip().encode("utf-8"))


@dataclass(frozen=True)
class AdapterUserOrigin:
    """One REAL UserPromptSubmit message, recorded verbatim, kind NOT guessed.

    ``kind`` stays None at capture time.  The model may later declare a control
    kind on top of this origin via ``declare_control``, which keeps the verbatim
    user text attached so the interpretation is auditable and correctable.
    """
    adapter_message_id: str
    session_id: str
    seq: int
    prompt_hash: str
    prompt_text: str            # verbatim user text (auditable anchor)
    kind: str | None            # filled only by an explicit model declaration
    payload: str | None         # CORRECTION body or None
    declared_by: str | None     # MODEL_INTERPRETATION_OF_REAL_USER_PROMPT when declared
    created_at: str

    def as_json(self) -> dict[str, Any]:
        return {
            "adapter_message_id": self.adapter_message_id,
            "session_id": self.session_id,
            "seq": self.seq,
            "prompt_hash": self.prompt_hash,
            "prompt_text": self.prompt_text,
            "kind": self.kind,
            "payload": self.payload,
            "declared_by": self.declared_by,
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
        entry = data.get(session_id, {"seq": 0, "used": [], "records": {}})
        if prompt_hash in entry["used"]:
            return entry["seq"], False
        entry["seq"] += 1
        entry["used"].append(prompt_hash)
        data[session_id] = entry
        self._save(data)
        return entry["seq"], True

    def remember(self, session_id: str, prompt_hash: str, seq: int, prompt_text: str) -> None:
        """Persist the verbatim text + seq of one captured message.

        The model's later declaration is checked against this record, so it can
        only ever act on a message the host actually delivered.
        """
        data = self._load()
        entry = data.get(session_id, {"seq": 0, "used": [], "records": {}})
        records = entry.setdefault("records", {})
        records[prompt_hash] = {"seq": seq, "text": prompt_text}
        data[session_id] = entry
        self._save(data)

    def record(self, session_id: str, prompt_hash: str) -> dict | None:
        """Return the stored record (seq/text) for a captured message, if any."""
        data = self._load()
        return data.get(session_id, {}).get("records", {}).get(prompt_hash)

    def forget(self, session_id: str, prompt_hash: str) -> None:
        """Remove one recorded prompt so a FAILED real message can be retried.

        Called by the bridge right after the Core rejected a genuine declared
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

    def declare(self, session_id: str, prompt_hash: str, kind: str) -> bool:
        """Atomically mark one real message as declared. False = already declared.

        One real user message can carry at most one model declaration; the second
        declaration is refused regardless of kind (PAUSE then CANCEL on the same
        message is a replay of authority, not a new instruction).
        """
        data = self._load()
        entry = data.get(session_id, {"seq": 0, "used": [], "declared": {}})
        declared = entry.setdefault("declared", {})
        if prompt_hash in declared:
            return False
        declared[prompt_hash] = kind
        data[session_id] = entry
        self._save(data)
        return True


def capture_user_prompt(payload: dict[str, Any], store: PromptStore) -> AdapterUserOrigin:
    """Record one REAL UserPromptSubmit verbatim.  Never guesses intent.

    This is the ONLY factory for a Harness-asserted User Origin.  Payload must be
    a genuine host UserPromptSubmit record (host origin tag, host session_id, raw
    user prompt).  The returned origin has ``kind=None`` until the model declares
    a control on top of it.
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
    store.remember(session_id, p_hash, seq, prompt)
    mid = "am-" + _sha256(f"{session_id}|{seq}|{p_hash}".encode("utf-8"))[:32] + f"-{seq}"
    return AdapterUserOrigin(
        adapter_message_id=mid,
        session_id=session_id,
        seq=seq,
        prompt_hash=p_hash,
        prompt_text=prompt,
        kind=None,
        payload=None,
        declared_by=None,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )


def declare_control(origin: AdapterUserOrigin, kind: str,
                    store: PromptStore,
                    payload: str | None = None) -> AdapterUserOrigin:
    """Model-side declaration that this REAL user message is a control.

    The model must point at a captured origin (a real user message it actually
    saw) and pick exactly one of PAUSE/RESUME/CANCEL/CORRECTION.  The verbatim
    ``prompt_text`` stays attached so the human can verify or reject the model's
    interpretation.  One real message may be declared at most once (tracked in
    the store); declaring twice is a replay of authority, not a new instruction.
    """
    if kind not in CONTROL_KINDS:
        raise ControlRejected(f"unknown control kind: {kind!r}")
    if kind == "CORRECTION":
        if not payload or not payload.strip():
            raise ControlRejected("correction requires content")
        ctrl_payload = payload.strip()
    else:
        ctrl_payload = None
    if not store.declare(origin.session_id, origin.prompt_hash, kind):
        raise ControlRejected(
            f"origin {origin.adapter_message_id} already declared; "
            "one real user message carries at most one control")
    return AdapterUserOrigin(
        adapter_message_id=origin.adapter_message_id,
        session_id=origin.session_id,
        seq=origin.seq,
        prompt_hash=origin.prompt_hash,
        prompt_text=origin.prompt_text,
        kind=kind,
        payload=ctrl_payload,
        declared_by=MODEL_DECLARED,
        created_at=origin.created_at,
    )


CONTROL_STATES = {"RUNNING", "PAUSED", "CANCELLED", "COMPLETED"}


@dataclass
class HumanAuthorityState:
    session_id: str
    state: str = "RUNNING"
    plan_revision: int = 1
    corrections: list[str] = field(default_factory=list)

    def apply(self, origin: AdapterUserOrigin, plan_revision: int | None = None) -> str:
        """Apply a control that was DECLARED by the model on a REAL user origin.

        Undeclared origins (kind is None) never move the state machine: the model
        must explicitly interpret the real message first.  Model prose, tool
        output, Stop and PostToolUse can never produce an origin at all.
        """
        if origin.session_id != self.session_id:
            raise ControlRejected("other-session user origin rejected")
        if origin.kind is None:
            return self.state  # captured but not declared: no state change
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
