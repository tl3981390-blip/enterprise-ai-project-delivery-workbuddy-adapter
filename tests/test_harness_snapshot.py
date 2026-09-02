"""Harness snapshot legality tests: only current-session Harness lists are candidates."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from harness_skill_snapshot import (SnapshotRejected, fingerprint, load_snapshot,
                                    parse_skill_entry, write_snapshot)

FIX = Path(__file__).parent / "fixtures" / "harness-skill-snapshot.baseline.json"


def test_baseline_fixture_loads_and_is_unique():
    snap = load_snapshot(FIX)
    assert snap.source == "skill_tool_available_skills"
    assert len({s.identity for s in snap.skills}) == len(snap.skills)
    assert snap.session_id


def test_illegal_source_rejected():
    data = json.loads(FIX.read_text(encoding="utf-8"))
    data["source"] = "mock_registry_i_wrote"
    p = FIX.parent / "illegal.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SnapshotRejected):
        load_snapshot(p)
    p.unlink()


def test_disk_scan_source_rejected():
    data = json.loads(FIX.read_text(encoding="utf-8"))
    data["source"] = "local_disk_scan_of_.workbuddy/skills"
    p = FIX.parent / "disk.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SnapshotRejected):
        load_snapshot(p)
    p.unlink()


def test_entry_without_description_rejected():
    with pytest.raises(SnapshotRejected):
        parse_skill_entry({"identity": "x", "description": "  "}, "skill_tool_available_skills")


def test_duplicate_identities_rejected():
    data = json.loads(FIX.read_text(encoding="utf-8"))
    data["skills"].append(dict(data["skills"][0]))
    p = FIX.parent / "dup.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SnapshotRejected):
        load_snapshot(p)
    p.unlink()


def test_fingerprint_stable_and_writes_roundtrip(tmp_path):
    snap = load_snapshot(FIX)
    out = tmp_path / "snap.json"
    write_snapshot(snap, out)
    again = load_snapshot(out)
    assert fingerprint(again) == fingerprint(snap)
