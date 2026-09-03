"""Guard against leaking the acceptance answer into model-facing prompts."""
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "tools" / "run_blackbox.py").read_text(
    encoding="utf-8")


def test_main_blackbox_goal_is_a_normal_user_goal():
    assert 'goal = "请接手当前项目，把它可靠地完成并交付给我。"' in SOURCE


def test_no_model_facing_attack_script_or_expected_answer_is_embedded():
    # Hostile/replay declarations belong in internal_declare(), never in a user turn.
    forbidden = (
        "（附验收指令：", "请用 Bash 把下面 JSON", "mid=本消息",
        "它必须因", "回报 bridge 输出",
    )
    assert all(text not in SOURCE for text in forbidden)
    assert "def internal_declare(" in SOURCE
