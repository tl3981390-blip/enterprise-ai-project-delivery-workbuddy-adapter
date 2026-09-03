"""The WorkBuddy demo must not require an unavailable Host capability."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from blackbox_project import CONTRACT, CLAUDE_MD


def test_workbuddy_demo_contract_has_only_host_supported_acceptance_items():
    assert {item["ac_id"] for item in CONTRACT} == {
        "REAL_HOST_EVENT_BRIDGE", "CANONICAL_EVIDENCE_LEDGER"
    }
    assert "HARNESS_SKILL_SELECTION" not in CLAUDE_MD
    assert "不要求也不允许伪造自动能力选择" in CLAUDE_MD
