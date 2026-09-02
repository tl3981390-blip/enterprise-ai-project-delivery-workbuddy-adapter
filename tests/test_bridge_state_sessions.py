"""Coverage #2: enabled projects create and restore project-scoped bridge state.

State is written strictly under the enabled project root, survives a re-load (new hook
process), binds a Controller Session on first sight, resumes it idempotently, and opens
a fresh episode when a closed session id comes back.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import bridge_state as bs  # noqa: E402
from project_gate import enabled_at  # noqa: E402

TS = "2026-09-02T10:00:00.000Z"
GATE = {"adapter": "enterprise-ai-project-delivery-workbuddy-adapter", "enabled": True}


def _enable(root: Path) -> None:
    target = root / ".workbuddy" / "delivery-contract.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(GATE), encoding="utf-8")
    assert enabled_at(root)


def _load(root: Path) -> dict:
    return bs.load_state(root)  # fresh process-equivalent read


def test_state_created_binds_and_persists(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _enable(root)
    assert bs.load_state(root) is None  # nothing before first hook activity

    state = bs.empty_state(root, TS)
    assert bs.bind_session(state, "sess-1", "startup", "/t/x.jsonl", TS) == "created"
    bs.save_state(root, state, TS)

    reloaded = _load(root)
    assert reloaded is not None
    entry = reloaded["sessions"]["sess-1"]
    assert entry["status"] == "active"
    assert entry["episode"] == 1
    assert entry["transcript_path"] == "/t/x.jsonl"
    assert bs.has_active_session(reloaded, "sess-1")

    # state file lives strictly under the project root
    assert (root / ".workbuddy" / "bridge" / "STATE.json").is_file()


def test_resume_is_idempotent_and_persisted(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _enable(root)
    state = bs.empty_state(root, TS)
    bs.bind_session(state, "sess-1", "startup", "", TS)
    bs.save_state(root, state, TS)

    reloaded = _load(root)
    # A later SessionStart for the same session resumes, not duplicates.
    assert bs.bind_session(reloaded, "sess-1", "startup", "/t/y.jsonl", TS) == "resumed"
    bs.save_state(root, reloaded, TS)

    final = _load(root)
    sessions = final["sessions"]
    assert len(sessions) == 1
    assert sessions["sess-1"]["status"] == "active"
    assert sessions["sess-1"]["episode"] == 1
    assert sessions["sess-1"]["transcript_path"] == "/t/y.jsonl"


def test_closed_session_reopens_as_fresh_episode(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _enable(root)
    state = bs.empty_state(root, TS)
    bs.bind_session(state, "sess-1", "startup", "", TS)
    assert bs.end_session(state, "sess-1", "other", TS) == "closed"
    bs.save_state(root, state, TS)

    reloaded = _load(root)
    assert not bs.has_active_session(reloaded, "sess-1")
    assert bs.bind_session(reloaded, "sess-1", "resume", "", TS) == "reopened"
    bs.save_state(root, reloaded, TS)

    final = _load(root)
    entry = final["sessions"]["sess-1"]
    assert entry["status"] == "active"
    assert entry["episode"] == 2
    assert entry["receipts"] == []  # old evidence never carries over


def test_audit_trail_is_append_only(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _enable(root)
    bs.append_audit(root, {"kind": "a", "n": 1}, TS)
    bs.append_audit(root, {"kind": "b", "n": 2}, TS)
    lines = (root / ".workbuddy" / "bridge" / "AUDIT.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["kind"] == "a"
    assert json.loads(lines[1])["kind"] == "b"
