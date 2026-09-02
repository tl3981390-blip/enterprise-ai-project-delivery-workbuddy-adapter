"""Invocation scope control — temporary context that MUST be cleaned up after a Work Unit.

Every selected-capability invocation gets a bounded scope: a temp context directory
and an audit entry. On scope exit the context directory is removed and a cleanup
receipt is appended to the audit log. No invocation context may leak into later Work
Units or ordinary conversation.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Iterator


class ScopeControl:
    def __init__(self, audit_dir: str | Path):
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def open_scope(self, session_id: str, work_unit: str, skill_identity: str) -> "InvocationScope":
        scope_id = f"{session_id[:8]}-{uuid.uuid4().hex[:12]}"
        ctx_dir = self.audit_dir / "scopes" / scope_id
        ctx_dir.mkdir(parents=True, exist_ok=True)
        self._audit({
            "event": "scope_opened",
            "scope_id": scope_id,
            "session_id": session_id,
            "work_unit": work_unit,
            "skill_identity": skill_identity,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
        return InvocationScope(self, scope_id, ctx_dir, session_id, work_unit, skill_identity)

    def close_scope(self, scope: "InvocationScope", outcome: str = "cleaned") -> None:
        if scope.ctx_dir.exists():
            for child in scope.ctx_dir.iterdir():
                if child.is_dir():
                    for sub in child.iterdir():
                        sub.unlink(missing_ok=True)
                    child.rmdir()
                else:
                    child.unlink(missing_ok=True)
            scope.ctx_dir.rmdir()
        self._audit({
            "event": "scope_closed",
            "scope_id": scope.scope_id,
            "session_id": scope.session_id,
            "work_unit": scope.work_unit,
            "skill_identity": scope.skill_identity,
            "context_dir_exists_after": scope.ctx_dir.exists(),
            "outcome": outcome,
            "closed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })

    def _audit(self, record: dict) -> None:
        path = self.audit_dir / "scope-audit.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


class InvocationScope:
    def __init__(self, control: ScopeControl, scope_id: str, ctx_dir: Path,
                 session_id: str, work_unit: str, skill_identity: str):
        self.control = control
        self.scope_id = scope_id
        self.ctx_dir = ctx_dir
        self.session_id = session_id
        self.work_unit = work_unit
        self.skill_identity = skill_identity
        self._closed = False

    def __enter__(self) -> "InvocationScope":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self, outcome: str = "cleaned") -> None:
        if self._closed:
            return
        self.control.close_scope(self, outcome=outcome)
        self._closed = True
