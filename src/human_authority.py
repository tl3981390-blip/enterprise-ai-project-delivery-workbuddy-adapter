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

Two-stage authority (fail-closed by construction):

* A declaration that the model itself judges AMBIGUOUS, or whose kind is the
  high-risk CANCEL / CORRECTION, NEVER moves the Core.  It only opens a
  ``Proposal`` (PROPOSED_CONTROL) that stays pending until a DIFFERENT, later
  REAL user message confirms it with the proposal_id and the same kind.
* The confirmation must be anchored on the real user message immediately after
  the proposal's message, in the same session, once only, and may never come
  from model prose, tool output, Stop or PostToolUse.
* Only PAUSE / RESUME that the model reads as CLEAR may apply directly, and
  even then the declaration must reference the newest REAL captured message.

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

VALID_AMBIGUITY_ASSESSMENTS = ("CLEAR", "AMBIGUOUS")
VALID_CONFIDENCE = ("LOW", "MEDIUM", "HIGH")
# CANCEL/CORRECTION are the highest-risk controls: even a CLEAR reading never
# applies directly; it opens a Proposal that requires a later real confirmation.
CONFIRM_GATED_KINDS = frozenset({"CANCEL", "CORRECTION"})
# The only channel that may anchor a control declaration is a REAL user prompt.
DECLARE_HOOK_EVENTS = frozenset({"UserPromptSubmit"})


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

    def remember(self, session_id: str, prompt_hash: str, seq: int, prompt_text: str,
                 at: str | None = None) -> None:
        """Persist the verbatim text + seq of one captured message.

        The model's later declaration is checked against this record, so it can
        only ever act on a message the host actually delivered.  ``at`` is the
        UTC capture time (used to decide which session owns the newest message).
        """
        if at is None:
            at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        data = self._load()
        entry = data.get(session_id, {"seq": 0, "used": [], "records": {}})
        records = entry.setdefault("records", {})
        records[prompt_hash] = {"seq": seq, "text": prompt_text, "at": at}
        data[session_id] = entry
        self._save(data)

    def newest_capture(self) -> tuple[str, dict] | None:
        """(session_id, record) owning the newest captured message across sessions.

        Declarations are only legal for the session whose real user message is
        the most recent capture in the project: authority must track the person
        actually talking now, and a different session can never revive an older
        session's messages.  Fail-closed under concurrency: the idle session
        loses.
        """
        data = self._load()
        best: tuple[str, dict] | None = None
        for sid, entry in data.items():
            for record in (entry.get("records") or {}).values():
                at = str(record.get("at") or "")
                if at and (best is None or at > best[1].get("at", "")):
                    best = (sid, record)
        return best

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

    def latest_seq(self, session_id: str) -> int:
        """Highest sequence number captured in this session (0 = nothing captured)."""
        data = self._load()
        return int(data.get(session_id, {}).get("seq", 0))

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


# --------------------------------------------------------------------------
# ControlDeclaration — the structured model input the governed channel accepts.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ControlDeclaration:
    """One model-side declaration/confirmation on a REAL captured user message.

    Required fields are enforced by :func:`parse_control_declaration` so that a
    bare ``{"kind": "CANCEL"}`` (or any under-specified pipe) can never reach the
    Core.  ``adapter_message_id`` and ``quoted_user_text`` anchor the
    declaration to a real host capture; the bridge re-verifies both.
    """
    session_id: str
    kind: str                                # PAUSE | RESUME | CANCEL | CORRECTION
    adapter_message_id: str                  # must equal the recomputed mid
    quoted_user_text: str                    # verbatim prompt the declaration is based on
    rationale: str
    ambiguity_assessment: str                # CLEAR | AMBIGUOUS
    impacted_scope: str
    confidence: str                          # LOW | MEDIUM | HIGH
    confirm_proposal_id: str | None = None   # set only when confirming a proposal

    def as_json(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "kind": self.kind,
            "adapter_message_id": self.adapter_message_id,
            "quoted_user_text": self.quoted_user_text,
            "rationale": self.rationale,
            "ambiguity_assessment": self.ambiguity_assessment,
            "impacted_scope": self.impacted_scope,
            "confidence": self.confidence,
            "confirm_proposal_id": self.confirm_proposal_id,
        }


def parse_control_declaration(raw: dict[str, Any]) -> ControlDeclaration:
    """Strictly validate one model declaration payload. Raises ControlRejected."""
    if not isinstance(raw, dict):
        raise ControlRejected("declaration_payload_not_object")
    hook_event = str(raw.get("hook_event_name") or "").strip()
    if hook_event not in DECLARE_HOOK_EVENTS:
        raise ControlRejected(
            f"invalid_control_channel:{hook_event or 'missing'}; "
            "only a REAL UserPromptSubmit capture may anchor a control")
    session_id = str(raw.get("session_id") or "").strip()
    kind = str(raw.get("kind") or "").strip().upper()
    mid = str(raw.get("adapter_message_id") or "").strip()
    prompt = str(raw.get("prompt") or raw.get("quoted_user_text") or "").strip()
    rationale = str(raw.get("rationale") or "").strip()
    assessment = str(raw.get("ambiguity_assessment") or "").strip().upper()
    confidence = str(raw.get("confidence") or "").strip().upper()
    impacted_scope = str(raw.get("impacted_scope") or "").strip()
    confirm_proposal_id = str(raw.get("confirm_proposal_id") or "").strip() or None
    if not session_id:
        raise ControlRejected("declaration_missing_session_id")
    if kind not in CONTROL_KINDS:
        raise ControlRejected(f"unknown_control_kind:{kind or 'missing'}")
    if not mid:
        raise ControlRejected("declaration_missing_adapter_message_id")
    if not prompt:
        raise ControlRejected("declaration_missing_quoted_user_text")
    if not rationale:
        raise ControlRejected("declaration_missing_rationale")
    if assessment not in VALID_AMBIGUITY_ASSESSMENTS:
        raise ControlRejected(f"invalid_ambiguity_assessment:{assessment or 'missing'}")
    if confidence not in VALID_CONFIDENCE:
        raise ControlRejected(f"invalid_confidence:{confidence or 'missing'}")
    if kind == "CORRECTION":
        correction_body = str(raw.get("payload") or "").strip()
        if not correction_body:
            raise ControlRejected("correction_requires_content")
        if not impacted_scope:
            impacted_scope = "user-stated correction (scope to be clarified on confirm)"
    return ControlDeclaration(
        session_id=session_id, kind=kind, adapter_message_id=mid,
        quoted_user_text=prompt, rationale=rationale,
        ambiguity_assessment=assessment, impacted_scope=impacted_scope,
        confidence=confidence, confirm_proposal_id=confirm_proposal_id)


def is_confirm_gated(kind: str, assessment: str) -> bool:
    """A declaration opens a Proposal (never touches Core) iff high-risk or unclear."""
    return kind in CONFIRM_GATED_KINDS or assessment == "AMBIGUOUS"


class ProposalRejected(Exception):
    """A proposal cannot be created/confirmed/consumed as requested."""


class ProposalStore:
    """Per-session, persistent proposal ledger (Adapter-governed, pre-Core).

    A Proposal is the only bridge between an ambiguous/high-risk model reading
    and a Core Human-Authority operation.  It is created WITHOUT touching the
    Core; only a later real confirmation consumes it and lets the bridge call
    the Core.  One message may open at most one proposal; one open proposal at
    a time per session; a proposal can only be confirmed by the immediately
    following real message of the same session.
    """

    PROPOSAL_STATUSES = ("OPEN", "CONSUMED", "EXPIRED", "SUPERSEDED", "REJECTED_CORE")

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # -- persistence -------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _proposals(self, session_id: str) -> list[dict[str, Any]]:
        return self._load().get(session_id, {}).get("proposals", [])

    def _put(self, session_id: str, proposals: list[dict[str, Any]]) -> None:
        data = self._load()
        entry = data.setdefault(session_id, {"proposals": []})
        entry["proposals"] = proposals
        data[session_id] = entry
        self._save(data)

    # -- queries -----------------------------------------------------------
    def open_proposal(self, session_id: str) -> dict[str, Any] | None:
        for proposal in self._proposals(session_id):
            if proposal.get("status") == "OPEN":
                return proposal
        return None

    def get(self, session_id: str, proposal_id: str) -> dict[str, Any] | None:
        for proposal in self._proposals(session_id):
            if proposal.get("proposal_id") == proposal_id:
                return proposal
        return None

    # -- lifecycle ---------------------------------------------------------
    def create(self, session_id: str, *, kind: str, source_adapter_message_id: str,
               source_seq: int, rationale: str, ambiguity_assessment: str,
               impacted_scope: str, confidence: str,
               correction_payload: str | None = None) -> dict[str, Any]:
        """Open a new Proposal; supersedes any currently OPEN one (audit trail).

        The Core is not touched here.  Returns the stored proposal record.
        """
        now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        proposals = self._proposals(session_id)
        for proposal in proposals:
            if proposal.get("status") == "OPEN":
                proposal["status"] = "SUPERSEDED"
                proposal["superseded_at"] = now
                proposal["superseded_reason"] = "new_proposal_opened"
        proposal_id = "prop-" + _sha256(
            f"{session_id}|{source_adapter_message_id}|{now}|{kind}".encode("utf-8"))[:16]
        record = {
            "proposal_id": proposal_id,
            "session_id": session_id,
            "kind": kind,
            "source_adapter_message_id": source_adapter_message_id,
            "source_seq": source_seq,
            "rationale": rationale,
            "ambiguity_assessment": ambiguity_assessment,
            "impacted_scope": impacted_scope,
            "confidence": confidence,
            "payload": correction_payload,
            "status": "OPEN",
            "created_at": now,
            "expires_after_seq": source_seq + 1,
            "confirm_adapter_message_id": None,
            "confirmed_at": None,
        }
        proposals.append(record)
        self._put(session_id, proposals)
        return record

    def supersede_open(self, session_id: str, reason: str) -> list[dict[str, Any]]:
        """Close any OPEN proposal of the session with a machine reason."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        changed = False
        proposals = self._proposals(session_id)
        for proposal in proposals:
            if proposal.get("status") == "OPEN":
                proposal["status"] = "SUPERSEDED"
                proposal["superseded_at"] = now
                proposal["superseded_reason"] = reason
                changed = True
        if changed:
            self._put(session_id, proposals)
        return [p for p in proposals if p.get("status") == "SUPERSEDED"]

    def expire_on_capture(self, session_id: str, seq: int) -> list[dict[str, Any]]:
        """Expire OPEN proposals that can no longer be confirmed by message ``seq``.

        A proposal may only be confirmed by the immediately following real
        message (``source_seq + 1``); if the user says anything else first, the
        proposal is dead (fail-closed: a stale confirmation can never apply).
        """
        now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        expired: list[dict[str, Any]] = []
        changed = False
        proposals = self._proposals(session_id)
        for proposal in proposals:
            if (proposal.get("status") == "OPEN"
                    and int(proposal.get("expires_after_seq", 0)) < seq):
                proposal["status"] = "EXPIRED"
                proposal["expired_at"] = now
                proposal["expired_reason"] = "newer_message_captured_before_confirmation"
                expired.append(proposal)
                changed = True
        if changed:
            self._put(session_id, proposals)
        return expired

    def validate_confirmation(self, session_id: str, proposal_id: str, *,
                              kind: str, ambiguity_assessment: str,
                              confirm_seq: int) -> dict[str, Any]:
        """Fail-closed checks before a confirmation may reach the Core."""
        proposal = self.get(session_id, proposal_id)
        if proposal is None:
            raise ProposalRejected("proposal_not_found")
        if proposal.get("status") != "OPEN":
            raise ProposalRejected(f"proposal_not_open:{proposal.get('status')}")
        if proposal.get("session_id") != session_id:
            raise ProposalRejected("proposal_other_session")
        if kind != proposal.get("kind"):
            raise ProposalRejected(
                f"confirmation_kind_mismatch:{kind}!={proposal.get('kind')}")
        if ambiguity_assessment != "CLEAR":
            raise ProposalRejected(
                "confirmation_ambiguous:an ambiguous message cannot confirm a proposal; "
                "ask the user for a clearer confirmation")
        if confirm_seq != int(proposal.get("expires_after_seq", -1)):
            raise ProposalRejected(
                f"confirmation_stale:proposal expires after seq "
                f"{proposal.get('expires_after_seq')}, confirmation is on seq {confirm_seq}")
        return proposal

    def consume(self, session_id: str, proposal_id: str,
                confirm_adapter_message_id: str) -> dict[str, Any]:
        now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        proposals = self._proposals(session_id)
        target = next((p for p in proposals if p.get("proposal_id") == proposal_id), None)
        if target is None or target.get("status") != "OPEN":
            raise ProposalRejected("proposal_not_open")
        target["status"] = "CONSUMED"
        target["confirm_adapter_message_id"] = confirm_adapter_message_id
        target["confirmed_at"] = now
        self._put(session_id, proposals)
        return target

    def reject_core(self, session_id: str, proposal_id: str, reason: str) -> None:
        proposal = self.get(session_id, proposal_id)
        if proposal is None or proposal.get("status") != "OPEN":
            return
        proposal["status"] = "REJECTED_CORE"
        proposal["core_reject_reason"] = reason
        self._put(session_id, self._proposals(session_id))

    def snapshot(self, session_id: str) -> list[dict[str, Any]]:
        return self._proposals(session_id)
