import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from probe_workbuddy import probe


def _write_formal_core(home: Path) -> None:
    core = home / "skills" / "enterprise-ai-project-delivery"
    core.mkdir(parents=True)
    (core / "SKILL.md").write_text("# delivery", encoding="utf-8")
    (core / "INSTALL_INFO.json").write_text(json.dumps({
        "skill_id": "enterprise-ai-project-delivery",
        "version": "3.0.6",
        "canonical_identity": "tag v3.0.6 -> commit " + "a" * 40,
    }), encoding="utf-8")


def test_preflight_separates_core_install_from_live_host_claims(tmp_path):
    _write_formal_core(tmp_path)
    result = probe(tmp_path)
    assert result["formal_core_installation"]["status"] == "PASS"
    assert result["project_scoped_controller"]["status"] == "PENDING_EXTERNAL_VALIDATION"
    assert result["automatic_harness_skill_selection"]["status"] == "NOT_INCLUDED_BY_DESIGN"
    assert result["enterprise_demo_scope"]["automatic_skill_selection_demo"].startswith("not eligible")


def test_preflight_fails_if_formal_core_is_absent(tmp_path):
    result = probe(tmp_path)
    assert result["formal_core_installation"] == {
        "status": "FAIL", "reason": "FORMAL_CORE_NOT_INSTALLED"
    }
    assert result["enterprise_demo_scope"]["status"] == "FAIL"
