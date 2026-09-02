"""Fail-closed Proposal/Confirmation layer (two-stage Human Authority).

These are deterministic unit tests of the module-level policy the bridge uses:
an AMBIGUOUS reading, and any CANCEL/CORRECTION, may only open a Proposal that
requires a later, different, real confirmation; stale/ambiguous/mismatched/
replayed confirmations are rejected; only CLEAR PAUSE/RESUME may apply directly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from human_authority import (ControlRejected, ProposalRejected, ProposalStore,
                             canonical_prompt_hash, is_confirm_gated,
                             parse_control_declaration)


def _decl(**overrides):
    raw = {
        "session_id": "sess-1",
        "prompt": "先这样吧，先停一下",
        "kind": "PAUSE",
        "adapter_message_id": "am-deadbeefdeadbeefdeadbeefdeadbeef-3",
        "rationale": "口语化暂停",
        "ambiguity_assessment": "AMBIGUOUS",
        "impacted_scope": "当前 stage",
        "confidence": "MEDIUM",
        "hook_event_name": "UserPromptSubmit",
    }
    raw.update(overrides)
    return raw


def test_declaration_requires_all_fields_and_legal_values():
    d = parse_control_declaration(_decl())
    assert d.kind == "PAUSE" and d.ambiguity_assessment == "AMBIGUOUS"
    assert d.adapter_message_id == "am-deadbeefdeadbeefdeadbeefdeadbeef-3"
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(kind=""))
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(kind="FLIP"))
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(adapter_message_id=""))
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(rationale=""))
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(ambiguity_assessment="MAYBE"))
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(confidence="SURE"))
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(session_id=""))
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(prompt=""))


def test_declaration_channel_must_be_real_user_prompt():
    # Model/tool/Stop may NEVER anchor a declaration (test #5).
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(hook_event_name="Stop"))
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(hook_event_name="PostToolUse"))
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(hook_event_name=""))


def test_correction_declaration_requires_content():
    with pytest.raises(ControlRejected):
        parse_control_declaration(_decl(kind="CORRECTION", payload=""))
    d = parse_control_declaration(
        _decl(kind="CORRECTION", payload="只统计华东区域"))
    assert d.kind == "CORRECTION"


def test_gating_matrix():
    # High-risk or unclear readings NEVER apply directly.
    assert is_confirm_gated("CANCEL", "CLEAR") is True
    assert is_confirm_gated("CANCEL", "AMBIGUOUS") is True
    assert is_confirm_gated("CORRECTION", "CLEAR") is True
    assert is_confirm_gated("CORRECTION", "AMBIGUOUS") is True
    assert is_confirm_gated("PAUSE", "AMBIGUOUS") is True
    assert is_confirm_gated("RESUME", "AMBIGUOUS") is True
    # Only CLEAR PAUSE/RESUME may apply directly.
    assert is_confirm_gated("PAUSE", "CLEAR") is False
    assert is_confirm_gated("RESUME", "CLEAR") is False


@pytest.fixture()
def store(tmp_path):
    return ProposalStore(tmp_path / "proposals.json")


def _open_one(store, seq=4, kind="PAUSE"):
    return store.create("sess-1", kind=kind,
                        source_adapter_message_id=f"am-{'0' * 32}-{seq}",
                        source_seq=seq, rationale="r",
                        ambiguity_assessment="AMBIGUOUS",
                        impacted_scope="stage", confidence="MEDIUM")


def test_proposal_created_without_consuming_and_only_one_open(store):
    p1 = _open_one(store, seq=4)
    assert p1["status"] == "OPEN"
    assert store.open_proposal("sess-1")["proposal_id"] == p1["proposal_id"]
    p2 = _open_one(store, seq=6, kind="CORRECTION")
    assert store.open_proposal("sess-1")["proposal_id"] == p2["proposal_id"]
    assert store.get("sess-1", p1["proposal_id"])["status"] == "SUPERSEDED"


def test_proposal_expires_when_any_other_message_comes_first(store):
    p1 = _open_one(store, seq=4)  # expires_after_seq = 5
    # capturing seq 5 keeps it confirmable; seq 6 kills it
    assert store.expire_on_capture("sess-1", 5) == []
    expired = store.expire_on_capture("sess-1", 6)
    assert [p["proposal_id"] for p in expired] == [p1["proposal_id"]]
    assert store.get("sess-1", p1["proposal_id"])["status"] == "EXPIRED"


def test_confirmation_requires_open_same_kind_clear_immediate_successor(store):
    p = _open_one(store, seq=4)
    # exact successor, same kind, CLEAR -> valid
    proposal = store.validate_confirmation(
        "sess-1", p["proposal_id"], kind="PAUSE",
        ambiguity_assessment="CLEAR", confirm_seq=5)
    assert proposal["proposal_id"] == p["proposal_id"]
    # kind mismatch
    with pytest.raises(ProposalRejected):
        store.validate_confirmation("sess-1", p["proposal_id"], kind="CANCEL",
                                    ambiguity_assessment="CLEAR", confirm_seq=5)
    # ambiguous confirmation is never allowed ("好/可以" must not multi-bind)
    with pytest.raises(ProposalRejected):
        store.validate_confirmation("sess-1", p["proposal_id"], kind="PAUSE",
                                    ambiguity_assessment="AMBIGUOUS", confirm_seq=5)
    # stale: confirmation on seq 6, not the immediate successor
    with pytest.raises(ProposalRejected):
        store.validate_confirmation("sess-1", p["proposal_id"], kind="PAUSE",
                                    ambiguity_assessment="CLEAR", confirm_seq=6)


def test_confirmation_consumes_proposal_exactly_once(store):
    p = _open_one(store, seq=4)
    store.validate_confirmation("sess-1", p["proposal_id"], kind="PAUSE",
                                ambiguity_assessment="CLEAR", confirm_seq=5)
    store.consume("sess-1", p["proposal_id"], "am-11111111111111111111111111111111-5")
    assert store.get("sess-1", p["proposal_id"])["status"] == "CONSUMED"
    # replay confirmation on any later message is refused
    with pytest.raises(ProposalRejected):
        store.validate_confirmation("sess-1", p["proposal_id"], kind="PAUSE",
                                    ambiguity_assessment="CLEAR", confirm_seq=7)


def test_unknown_and_other_session_proposals_rejected(store):
    with pytest.raises(ProposalRejected):
        store.validate_confirmation("sess-1", "prop-missing", kind="PAUSE",
                                    ambiguity_assessment="CLEAR", confirm_seq=5)
    p = _open_one(store, seq=4)
    with pytest.raises(ProposalRejected):
        store.validate_confirmation("sess-other", p["proposal_id"], kind="PAUSE",
                                    ambiguity_assessment="CLEAR", confirm_seq=5)


def test_supersede_open_by_new_intent(store):
    p = _open_one(store, seq=4)
    superseded = store.supersede_open("sess-1", "new_intent_on_successor")
    assert [x["proposal_id"] for x in superseded] == [p["proposal_id"]]
    assert store.open_proposal("sess-1") is None


def test_hashes_stable_for_verbatim_quote_anchor():
    h1 = canonical_prompt_hash(" 先这样吧  ")
    h2 = canonical_prompt_hash("先这样吧")
    assert h1 == h2  # canonicalisation strips outer whitespace only
