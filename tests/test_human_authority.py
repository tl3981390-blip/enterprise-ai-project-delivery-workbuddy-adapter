"""Human Authority Controller tests — real UserPromptSubmit-origin only.

Contract under test:
- The adapter NEVER guesses intent.  Natural-language understanding is the
  MODEL's job.  The adapter records real user messages verbatim and only acts on
  an explicit model DECLARATION anchored to a real origin.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from human_authority import (AdapterUserOrigin, ControlRejected,
                             HumanAuthorityState, NotUserOrigin, PromptStore,
                             ReplayRejected, capture_user_prompt, declare_control)


def _user_payload(prompt: str, session: str = "s1") -> dict:
    return {"origin": "UserPromptSubmit", "session_id": session, "prompt": prompt}


def test_only_user_prompt_submit_can_assert_origin(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    for bad_origin in ("model", "PostToolUse", "Stop", "tool_output", "UserPromptSubmit_fake"):
        payload = dict(_user_payload("别干了"))
        payload["origin"] = bad_origin
        with pytest.raises(NotUserOrigin):
            capture_user_prompt(payload, store)


def test_missing_session_or_prompt_rejected(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    with pytest.raises(NotUserOrigin):
        capture_user_prompt({"origin": "UserPromptSubmit", "session_id": "", "prompt": "x"}, store)
    with pytest.raises(NotUserOrigin):
        capture_user_prompt({"origin": "UserPromptSubmit", "session_id": "s1", "prompt": "  "}, store)


def test_capture_is_verbatim_and_kind_stays_none(tmp_path):
    """The adapter must NOT interpret natural language. Capture is verbatim."""
    store = PromptStore(tmp_path / "store.json")
    origin = capture_user_prompt(_user_payload("停停停，先别继续了"), store)
    assert origin.kind is None                       # NOT auto-classified
    assert origin.prompt_text == "停停停，先别继续了"   # verbatim anchor kept
    assert origin.declared_by is None


def test_no_state_change_without_model_declaration(tmp_path):
    """A real message alone never moves the state machine; the model must declare."""
    store = PromptStore(tmp_path / "store.json")
    state = HumanAuthorityState(session_id="s1")
    origin = capture_user_prompt(_user_payload("先停一下"), store)
    state.apply(origin)                              # kind None -> no change
    assert state.state == "RUNNING"
    assert state.corrections == []


def test_model_declares_pause_then_resume_on_real_message(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    state = HumanAuthorityState(session_id="s1")

    # Real user text: whatever the model understood it as.
    pause_origin = capture_user_prompt(_user_payload("停停停，先别继续了"), store)
    declared = declare_control(pause_origin, "PAUSE", store)
    assert declared.kind == "PAUSE"
    assert declared.declared_by == "MODEL_INTERPRETATION_OF_REAL_USER_PROMPT"
    assert declared.prompt_text == "停停停，先别继续了"  # anchor still attached
    state.apply(declared)
    assert state.state == "PAUSED"

    # model cannot resume from model prose: no origin at all
    with pytest.raises(NotUserOrigin):
        capture_user_prompt({"origin": "model", "prompt": "继续", "session_id": "s1"}, store)
    assert state.state == "PAUSED"

    resume_origin = capture_user_prompt(_user_payload("好，接着弄吧"), store)
    state.apply(declare_control(resume_origin, "RESUME", store))
    assert state.state == "RUNNING"

    cancel_origin = capture_user_prompt(_user_payload("算了，不做了"), store)
    state.apply(declare_control(cancel_origin, "CANCEL", store))
    assert state.state == "CANCELLED"


def test_correction_requires_content_and_model_anchor(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    state = HumanAuthorityState(session_id="s1")
    origin = capture_user_prompt(_user_payload("优先修缺陷再补测试，报告要带验证命令"), store)
    with pytest.raises(ControlRejected):
        declare_control(origin, "CORRECTION", store, payload="   ")   # empty correction refused
    declared = declare_control(origin, "CORRECTION", store, payload="优先修缺陷再补测试，报告要带验证命令")
    state.apply(declared, plan_revision=2)
    assert state.corrections == ["优先修缺陷再补测试，报告要带验证命令"]
    assert state.plan_revision == 2


def test_one_real_message_declared_once(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    origin = capture_user_prompt(_user_payload("先停"), store)
    declare_control(origin, "PAUSE", store)
    with pytest.raises(ControlRejected):
        declare_control(origin, "CANCEL", store)     # re-declaration refused


def test_replay_rejected_across_restart(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    store2 = PromptStore(tmp_path / "store.json")  # same file -> simulates restart
    capture_user_prompt(_user_payload("先停"), store)
    with pytest.raises(ReplayRejected):
        capture_user_prompt(_user_payload("先停"), store2)


def test_other_session_rejected(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    state = HumanAuthorityState(session_id="s1")
    other = capture_user_prompt(_user_payload("先停", session="s2"), store)
    declared = declare_control(other, "PAUSE", store)
    with pytest.raises(ControlRejected):
        state.apply(declared)


def test_unknown_kind_rejected(tmp_path):
    store = PromptStore(tmp_path / "store.json")
    origin = capture_user_prompt(_user_payload("先停"), store)
    with pytest.raises(ControlRejected):
        declare_control(origin, "MAYBE_PAUSE", store)
