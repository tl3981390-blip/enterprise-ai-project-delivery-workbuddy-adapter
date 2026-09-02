"""Human Authority Controller tests — real UserPromptSubmit-origin only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from human_authority import (AdapterUserOrigin, ControlRejected, HumanAuthorityState,
                             NotUserOrigin, PromptStore, ReplayRejected,
                             classify_control, originate_user_prompt)


def _user_payload(prompt: str, session: str = "s1") -> dict:
    return {"origin": "UserPromptSubmit", "session_id": session, "prompt": prompt}


def test_only_user_prompt_submit_can_assert_origin(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    for bad_origin in ("model", "PostToolUse", "Stop", "tool_output", "UserPromptSubmit_fake"):
        payload = dict(_user_payload("继续交付"))
        payload["origin"] = bad_origin
        with pytest.raises(NotUserOrigin):
            originate_user_prompt(payload, store)


def test_missing_session_or_prompt_rejected(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    with pytest.raises(NotUserOrigin):
        originate_user_prompt({"origin": "UserPromptSubmit", "session_id": "", "prompt": "x"}, store)
    with pytest.raises(NotUserOrigin):
        originate_user_prompt({"origin": "UserPromptSubmit", "session_id": "s1", "prompt": "  "}, store)


def test_pause_resume_cancel_correction_roundtrip(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    state = HumanAuthorityState(session_id="s1")
    state.apply(originate_user_prompt(_user_payload("暂停交付"), store))
    assert state.state == "PAUSED"

    # model cannot resume: any non-UserPromptSubmit origin raises before apply
    with pytest.raises(NotUserOrigin):
        originate_user_prompt({"origin": "model", "prompt": "继续交付", "session_id": "s1"}, store)
    # a model RESTATEMENT through a fake origin is refused at the origin layer
    assert state.state == "PAUSED"

    state.apply(originate_user_prompt(_user_payload("继续交付"), store))
    assert state.state == "RUNNING"

    state.apply(originate_user_prompt(_user_payload("取消交付"), store))
    assert state.state == "CANCELLED"


def test_correction_and_model_cannot_forge(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    state = HumanAuthorityState(session_id="s1")
    origin = originate_user_prompt(_user_payload("记录纠正：优先修复缺陷再补测试"), store)
    assert origin.kind == "CORRECTION"
    state.apply(origin, plan_revision=2)
    assert state.corrections == ["优先修复缺陷再补测试"]
    assert state.plan_revision == 2

    # model cannot forge a correction through any non-hook channel
    forged = {"origin": "model_inference", "session_id": "s1", "prompt": "记录纠正：假纠正"}
    with pytest.raises(NotUserOrigin):
        originate_user_prompt(forged, store)
    assert state.corrections == ["优先修复缺陷再补测试"]


def test_ambiguous_or_plain_prompts_are_not_controls(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    state = HumanAuthorityState(session_id="s1")
    for text in ("能暂停吗？", "我想继续", "继续吧大概", "帮我总结一下",
                 "继续交付"):  # exact-only: last one IS a control
        pass
    # vague variants produce NO control kind
    for text in ("能暂停吗？", "我想继续", "继续吧大概", "帮我总结一下"):
        origin = originate_user_prompt(_user_payload(text), store)
        assert origin.kind is None
        assert state.state == "RUNNING"


def test_replay_rejected_across_restart(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    store2 = PromptStore(tmp_path / "store.json")  # same file -> simulates restart
    originate_user_prompt(_user_payload("暂停交付"), store)
    with pytest.raises(ReplayRejected):
        originate_user_prompt(_user_payload("暂停交付"), store2)


def test_other_session_rejected(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    state = HumanAuthorityState(session_id="s1")
    other = originate_user_prompt(_user_payload("暂停交付", session="s2"), store)
    with pytest.raises(ControlRejected):
        state.apply(other)


def test_correction_needs_content(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    with pytest.raises(ControlRejected):
        originate_user_prompt(_user_payload("记录纠正：   "), store)


def test_control_phrases_are_exact(tmp_path):
    assert classify_control("暂停交付") == ("PAUSE", None)
    assert classify_control("暂停交付 ") == ("PAUSE", None)
    assert classify_control("暂停交付啊") is None
