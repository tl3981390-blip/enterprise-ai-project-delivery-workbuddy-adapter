"""Harness Skill Snapshot — the ONLY legal candidate source for the Capability Router.

Rules enforced here (mirror of the WorkBuddy full-delivery contract):

1. Candidates may only come from what the current WorkBuddy / Harness session actually
   exposes through its Skill tool / available_skills list. Local workspace scans,
   drive scans, ``.workbuddy/skills`` disk walks, hand-written mock registries,
   fixed skill names and "I guess this harness has …" guesses are NOT legal sources.
2. A snapshot must therefore declare its ``source``; anything that is not a
   harness-provided list is rejected.
3. A candidate only counts as ``verified_callable`` after a REAL Skill-tool
   invocation succeeded in this session. Listing alone never implies verifiability.
4. Version is recorded only if the Harness actually provides it; otherwise the field
   is ``null`` and identity is evaluated against what the Harness exposes.

This module performs no I/O of its own against skill directories.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALLOWED_SOURCES = {"skill_tool_available_skills", "harness_available_skills"}


class SnapshotRejected(Exception):
    """The provided snapshot is not a trustworthy harness-session skill list."""


@dataclass(frozen=True)
class SkillCandidate:
    identity: str            # skill identity as exposed by the Harness
    description: str         # description as exposed by the Harness
    version: str | None      # only if the Harness provided one
    available: bool          # listed as callable in the current session
    permission: str          # "granted" | "denied" | "unknown"
    verified_callable: bool  # True ONLY after a real invocation record exists
    source: str              # provenance tag, must be an ALLOWED_SOURCE

    def to_row(self, wu_text: str = "") -> dict[str, Any]:
        return {
            "identity": self.identity,
            "description": self.description[:120],
            "version": self.version,
            "available": self.available,
            "permission": self.permission,
            "verified_callable": self.verified_callable,
            "source": self.source,
        }


@dataclass(frozen=True)
class HarnessSnapshot:
    harness: str
    session_id: str
    captured_at: str
    source: str
    skills: tuple[SkillCandidate, ...] = field(default_factory=tuple)

    def as_json(self) -> dict[str, Any]:
        return {
            "harness": self.harness,
            "session_id": self.session_id,
            "captured_at": self.captured_at,
            "source": self.source,
            "skill_count": len(self.skills),
            "skills": [s.to_row() for s in self.skills],
        }


def parse_skill_entry(raw: dict[str, Any], source: str) -> SkillCandidate:
    identity = str(raw.get("identity") or raw.get("name") or "").strip()
    if not identity:
        raise SnapshotRejected("skill entry missing identity/name")
    description_raw = str(raw.get("description") or "")
    if not description_raw.strip():
        raise SnapshotRejected(f"skill '{identity}' missing description")
    description = description_raw  # store verbatim: stripping would break fingerprint stability
    available = bool(raw.get("available", True))
    permission = str(raw.get("permission", "unknown"))
    verified = bool(raw.get("verified_callable", False))
    version = raw.get("version")
    if version is not None:
        version = str(version).strip() or None
    return SkillCandidate(
        identity=identity,
        description=description,
        version=version,
        available=available,
        permission=permission if permission in ("granted", "denied", "unknown") else "unknown",
        verified_callable=verified,
        source=source,
    )


def load_snapshot(path: str | Path) -> HarnessSnapshot:
    """Load and strictly validate a raw Harness Skill Snapshot file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    source = str(data.get("source") or "").strip()
    if source not in ALLOWED_SOURCES:
        raise SnapshotRejected(
            f"illegal candidate source '{source}'; only current-session Harness lists are legal")
    session_id = str(data.get("session_id") or "").strip()
    harness = str(data.get("harness") or "workbuddy").strip()
    captured_at = str(data.get("captured_at") or "").strip()
    raw_skills = data.get("skills")
    if not isinstance(raw_skills, list) or not raw_skills:
        raise SnapshotRejected("snapshot has no skills")
    skills = tuple(parse_skill_entry(entry, source) for entry in raw_skills)
    if len({s.identity for s in skills}) != len(skills):
        raise SnapshotRejected("duplicate skill identity in snapshot")
    return HarnessSnapshot(harness=harness, session_id=session_id,
                           captured_at=captured_at, source=source, skills=skills)


def fingerprint(snapshot: HarnessSnapshot) -> str:
    """Deterministic fingerprint of the raw snapshot (audit artifact)."""
    blob = json.dumps(snapshot.as_json(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def write_snapshot(snapshot: HarnessSnapshot, path: str | Path) -> None:
    payload = snapshot.as_json()
    payload["fingerprint_sha256"] = fingerprint(snapshot)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
