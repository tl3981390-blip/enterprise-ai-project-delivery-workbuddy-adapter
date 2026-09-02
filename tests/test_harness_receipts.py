"""HARNESS_EXECUTION receipt + Evidence Ledger + completion gate tests."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from harness_receipts import (EvidenceLedger, ReceiptRejected,
                              receipt_from_posttooluse)


def _tool_payload(output="region breakdown ok: {East: 600.0}"):
    return {
        "hook_origin": "PostToolUse",
        "tool_name": "Bash",
        "tool_use_id": "toolu_01_real",
        "output_text": output,
    }


def test_receipt_only_from_posttooluse():
    payload = dict(_tool_payload())
    payload["hook_origin"] = "Stop"
    with pytest.raises(ReceiptRejected):
        receipt_from_posttooluse(payload, session_id="s1", work_unit="wu1",
                                 plan_revision=1, skill_identity="k")

    payload["hook_origin"] = "model_self_report"
    with pytest.raises(ReceiptRejected):
        receipt_from_posttooluse(payload, session_id="s1", work_unit="wu1",
                                 plan_revision=1, skill_identity="k")


def test_receipt_rejects_marker_only_verdict():
    for marker in ("PASS", "OK", "SUCCESS", "{}"):
        with pytest.raises(ReceiptRejected):
            receipt_from_posttooluse(_tool_payload(output=marker), session_id="s1",
                                     work_unit="wu1", plan_revision=1, skill_identity="k")


def test_receipt_requires_output_and_tool_id():
    payload = dict(_tool_payload())
    payload.pop("tool_use_id", None)
    with pytest.raises(ReceiptRejected):
        receipt_from_posttooluse(payload, session_id="s1", work_unit="wu1",
                                 plan_revision=1, skill_identity="k")


def test_receipt_digest_binds_real_output(tmp_path):
    rec = receipt_from_posttooluse(_tool_payload(), session_id="s1", work_unit="wu1",
                                   plan_revision=1, skill_identity="git-k", skill_version="v1")
    assert rec.receipt_id.startswith("hrx-")
    assert rec.output_sha256 == __import__("hashlib").sha256(
        b"region breakdown ok: {East: 600.0}").hexdigest()
    assert rec.skill_identity == "git-k"


def test_ledger_rejects_other_session_and_replay(tmp_path):
    ledger = EvidenceLedger("s1", tmp_path / "ledger.json").load()
    rec = receipt_from_posttooluse(_tool_payload(), session_id="s1", work_unit="wu1",
                                   plan_revision=1, skill_identity="git-k")
    ledger.append(rec)
    with pytest.raises(ReceiptRejected):
        EvidenceLedger("other-session", tmp_path / "ledger.json").load()

    rec2 = receipt_from_posttooluse(_tool_payload(output="second run output"), session_id="s1",
                                    work_unit="wu1", plan_revision=1, skill_identity="git-k")
    ledger.append(rec2)
    with pytest.raises(ReceiptRejected):
        ledger.append(rec2)  # replay of same receipt


def test_replayed_tool_event_same_id_and_output_rejected(tmp_path):
    """The same real tool event (tool_use_id + output) never enters twice, even if the
    receipt chain link differs (previous receipt hash different => different receipt_id)."""
    ledger = EvidenceLedger("s1", tmp_path / "ledger.json").load()
    rec = receipt_from_posttooluse(_tool_payload(), session_id="s1", work_unit="wu1",
                                   plan_revision=1, skill_identity="git-k")
    ledger.append(rec)
    forged_link = receipt_from_posttooluse(_tool_payload(), session_id="s1", work_unit="wu1",
                                           plan_revision=1, skill_identity="git-k",
                                           prev_receipt_sha256="some-other-link")
    assert forged_link.receipt_id != rec.receipt_id
    with pytest.raises(ReceiptRejected):
        ledger.append(forged_link)


def test_completion_gate_refuses_missing_evidence(tmp_path):
    ledger = EvidenceLedger("s1", tmp_path / "ledger.json").load()
    rec = receipt_from_posttooluse(_tool_payload(), session_id="s1", work_unit="wu-git",
                                   plan_revision=1, skill_identity="git-state-change-regression")
    ledger.append(rec)
    allowed, missing = ledger.completion_gate([
        ("wu-git", "git-state-change-regression"),
        ("wu-fix", "enterprise-ai-project-delivery"),
    ])
    assert allowed is False
    assert missing == ["wu-fix:enterprise-ai-project-delivery"]


def test_completion_gate_allows_only_with_full_evidence(tmp_path):
    ledger = EvidenceLedger("s1", tmp_path / "ledger.json").load()
    rec = receipt_from_posttooluse(_tool_payload(), session_id="s1", work_unit="wu-git",
                                   plan_revision=1, skill_identity="git-state-change-regression")
    ledger.append(rec)
    allowed, missing = ledger.completion_gate([("wu-git", "git-state-change-regression")])
    assert allowed is True and missing == []
