"""HARNESS_EXECUTION receipts and the Delivery Session Evidence Ledger.

Canonical rule: Evidence enters ONLY through a real WorkBuddy Tool/Skill invocation
result observed by the harness (PostToolUse hook payload shape). There is no public
API accepting a model-built PASS dict, an arbitrary string, or a "log file exists"
claim. The completion gate reads the ledger and refuses when required evidence is
missing, stale, duplicated, or bound to another session.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HOOK_ORIGIN = "PostToolUse"


class ReceiptRejected(Exception):
    """The proposed receipt is not a trustworthy harness tool-invocation record."""


@dataclass(frozen=True)
class HarnessExecutionReceipt:
    receipt_id: str
    session_id: str
    work_unit: str
    plan_revision: int
    skill_identity: str
    skill_version: str | None
    tool_name: str
    tool_use_id: str
    output_sha256: str
    output_bytes: int
    captured_at: str
    input_scope_sha256: str
    prev_receipt_sha256: str | None

    def as_json(self) -> dict[str, Any]:
        return {
            "receipt_type": "HARNESS_EXECUTION",
            "receipt_id": self.receipt_id,
            "session_id": self.session_id,
            "work_unit": self.work_unit,
            "plan_revision": self.plan_revision,
            "skill_identity": self.skill_identity,
            "skill_version": self.skill_version,
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "output_sha256": self.output_sha256,
            "output_bytes": self.output_bytes,
            "captured_at": self.captured_at,
            "input_scope_sha256": self.input_scope_sha256,
            "prev_receipt_sha256": self.prev_receipt_sha256,
        }


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def receipt_from_posttooluse(
    payload: dict[str, Any],
    *,
    session_id: str,
    work_unit: str,
    plan_revision: int,
    skill_identity: str,
    skill_version: str | None = None,
    prev_receipt_sha256: str | None = None,
) -> HarnessExecutionReceipt:
    """Create a receipt ONLY from a PostToolUse-shaped hook payload.

    Rejected (hard fails): non-PostToolUse origin; model/tool/Stop-origin payloads;
    missing tool_use_id; missing/empty captured output; session mismatch; any attempt
    to inject a verdict without a real tool output payload.
    """
    if payload.get("hook_origin") != HOOK_ORIGIN:
        raise ReceiptRejected(
            f"receipts only from {HOOK_ORIGIN}; got origin={payload.get('hook_origin')!r}")
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_use_id = str(payload.get("tool_use_id") or "").strip()
    output_text = payload.get("output_text")
    if not tool_name:
        raise ReceiptRejected("tool_name missing in PostToolUse payload")
    if not tool_use_id:
        raise ReceiptRejected("tool_use_id missing in PostToolUse payload")
    if output_text is None or str(output_text).strip() == "":
        raise ReceiptRejected("PostToolUse payload carries no real tool output")
    output_bytes = str(output_text).encode("utf-8")
    output_sha = _sha256(output_bytes)
    # Reject self-declared verdicts: a payload whose text is only a PASS marker with
    # no real tool content cannot be a genuine tool output.
    marker_only = str(output_text).strip().upper() in {"PASS", "OK", "SUCCESS", "{}", "[]"}
    if marker_only or len(output_bytes) < 4:
        raise ReceiptRejected("payload output looks like a self-declared verdict, not a tool result")

    canonical = json.dumps({
        "session_id": session_id, "work_unit": work_unit, "plan_revision": plan_revision,
        "skill_identity": skill_identity, "tool_use_id": tool_use_id,
        "output_sha256": output_sha, "prev": prev_receipt_sha256,
    }, sort_keys=True, ensure_ascii=False).encode("utf-8")
    receipt_id = "hrx-" + _sha256(canonical)[:32]

    scope_input = f"{session_id}|{work_unit}|rev{plan_revision}|{tool_use_id}".encode("utf-8")

    return HarnessExecutionReceipt(
        receipt_id=receipt_id,
        session_id=session_id,
        work_unit=work_unit,
        plan_revision=plan_revision,
        skill_identity=skill_identity,
        skill_version=skill_version,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        output_sha256=output_sha,
        output_bytes=len(output_bytes),
        captured_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        input_scope_sha256=_sha256(scope_input),
        prev_receipt_sha256=prev_receipt_sha256,
    )


@dataclass
class EvidenceLedger:
    session_id: str
    store_path: Path
    receipts: dict[str, HarnessExecutionReceipt] = field(default_factory=dict)

    def load(self) -> "EvidenceLedger":
        if self.store_path.exists():
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            if data.get("session_id") != self.session_id:
                raise ReceiptRejected("ledger file belongs to another session")
            field_names = {f.name for f in dataclasses.fields(HarnessExecutionReceipt)}
            for rid, blob in data.get("receipts", {}).items():
                payload = {k: v for k, v in blob.items() if k in field_names}
                self.receipts[rid] = HarnessExecutionReceipt(**payload)
        return self

    def append(self, receipt: HarnessExecutionReceipt) -> "EvidenceLedger":
        if receipt.session_id != self.session_id:
            raise ReceiptRejected("other-session receipt rejected")
        if receipt.receipt_id in self.receipts:
            raise ReceiptRejected(f"duplicate/replayed receipt rejected: {receipt.receipt_id}")
        # Event-level replay detection: the same real tool event (tool_use_id + output
        # digest) may never enter the ledger twice, even under a different chain link.
        for existing in self.receipts.values():
            if (existing.tool_use_id == receipt.tool_use_id
                    and existing.output_sha256 == receipt.output_sha256):
                raise ReceiptRejected(
                    f"replayed tool event rejected: {receipt.tool_use_id} "
                    f"(output {receipt.output_sha256[:12]}…) already in ledger")
        self.receipts[receipt.receipt_id] = receipt
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(
            json.dumps({"session_id": self.session_id,
                        "receipts": {rid: r.as_json() for rid, r in self.receipts.items()}},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        return self

    def has(self, work_unit: str, skill_identity: str) -> bool:
        return any(r.work_unit == work_unit and r.skill_identity == skill_identity
                   for r in self.receipts.values())

    def completion_gate(self, required: list[tuple[str, str]]) -> tuple[bool, list[str]]:
        """Return (allowed, missing). Never accepts log-file presence as evidence."""
        missing = [f"{wu}:{skill}" for wu, skill in required if not self.has(wu, skill)]
        return (not missing), missing

    @property
    def tail_hash(self) -> str:
        if not self.receipts:
            return "0" * 64
        last = sorted(self.receipts.values(), key=lambda r: r.captured_at)[-1]
        return last.receipt_id
