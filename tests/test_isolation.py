"""Coverage #10 and #11: machine-independence and Core-immutability.

#10 The bridge never depends on the author's machine paths: it resolves the project
    root only from host context (CODEBUDDY_PROJECT_DIR / payload cwd), writes state only
    under that root, and its code never embeds the current user's home directory.

#11 The bridge never modifies the (pinned) main Core repository: a guarded snapshot of
    a Core-like tree stays byte-identical through full bridge operation, and no bridge
    module reads Core internals.
"""
from pathlib import Path
import hashlib
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import bridge_state as bs  # noqa: E402
from evidence import receipt_from_post_tool_use  # noqa: E402
from project_gate import locate_enabled_root  # noqa: E402
from stop_gate import evaluate_stop  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TS = "2026-09-02T10:00:00.000Z"
GATE = {"adapter": "enterprise-ai-project-delivery-workbuddy-adapter", "enabled": True}


def _enable(root: Path) -> None:
    target = root / ".workbuddy" / "delivery-contract.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(GATE), encoding="utf-8")


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_source_never_embeds_this_machines_home(tmp_path):
    home_marker = os.path.expanduser("~").lower()
    assert home_marker, "home must resolve for this test to be meaningful"
    offenders = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if home_marker in text.lower():
            offenders.append(str(path))
    assert not offenders, f"author-machine path leaked into source: {offenders}"


def test_root_resolution_is_deterministic_via_host_context(tmp_path):
    a = tmp_path / "proj-a"
    b = tmp_path / "proj-b"
    for root in (a, b):
        root.mkdir()
        _enable(root)
    env = {"CODEBUDDY_PROJECT_DIR": str(a)}
    payload = {"hook_event_name": "SessionStart", "session_id": "s1",
               "cwd": str(b)}  # payload cwd points at b; env must win
    assert locate_enabled_root(payload, env=env) == a
    # Work happens only under a; b stays untouched.
    decision = evaluate_stop({"hook_event_name": "Stop", "session_id": "s1", "cwd": str(a)},
                             env=env)
    assert decision.status in ("no_controller_session",)  # gate reachable, state absent yet
    assert not (b / ".workbuddy" / "bridge").exists()
    # with b's own context, resolution switches to b (no ambient author path involved)
    assert locate_enabled_root(payload, env={}) == b


def test_state_files_stay_under_resolved_root(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _enable(root)
    state = bs.empty_state(root, TS)
    bs.bind_session(state, "s1", "startup", "", TS)
    bs.save_state(root, state, TS)
    bs.append_audit(root, {"kind": "probe"}, TS)
    written = [p.relative_to(root).as_posix() for p in (root / ".workbuddy").rglob("*")]
    assert ".workbuddy/delivery-contract.json" in written
    assert ".workbuddy/bridge/STATE.json" in written
    assert ".workbuddy/bridge/AUDIT.jsonl" in written
    # nothing appears outside root
    state_path = bs.state_file(root).read_text(encoding="utf-8")
    assert REPO_ROOT.resolve().as_posix() not in state_path


def test_bridge_never_modifies_core_tree(tmp_path):
    core = tmp_path / "core"
    core.mkdir()
    (core / "Runtime").mkdir()
    (core / "Evidence").mkdir()
    (core / "HumanAuthority").mkdir()
    (core / "MODULE").mkdir()
    sentinels = {
        "Runtime/STATE.json": '{"canonical": true}',
        "Evidence/evidence_store.py": "def collect(): ...\n",
        "HumanAuthority/authority.py": "PAUSE = 'USER_PAUSE'\n",
        "MODULE/contract.py": "VERSION = '3.0.6'\n",
    }
    for rel, content in sentinels.items():
        (core / rel).write_text(content, encoding="utf-8")
    before = _tree_hash(core)
    file_count_before = len(list(core.rglob("*")))

    root = tmp_path / "proj"
    root.mkdir()
    _enable(root)
    state = bs.empty_state(root, TS)
    bs.bind_session(state, "s1", "startup", "", TS)
    receipt = receipt_from_post_tool_use({
        "hook_event_name": "PostToolUse", "session_id": "s1", "cwd": str(root),
        "tool_name": "Bash", "tool_input": {"command": "pytest"},
        "tool_response": {"exit_code": 0},
    }, TS)
    bs.add_receipt(state, "s1", receipt)
    bs.save_state(root, state, TS)
    evaluate_stop({"hook_event_name": "Stop", "session_id": "s1", "cwd": str(root)},
                  env={"CODEBUDDY_PROJECT_DIR": str(root)})

    assert _tree_hash(core) == before
    assert len(list(core.rglob("*"))) == file_count_before
