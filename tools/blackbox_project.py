#!/usr/bin/env python3
"""Build the disposable isolated black-box project for the REAL hook acceptance.

A fresh project directory (default under the OS temp dir) receives:
- official project-scoped command hooks (UserPromptSubmit/PostToolUse/Stop) that
  really execute the Adapter bridge (python -B so no bytecode is ever written
  into the formal Core install);
- CLAUDE.md that tells the session model how the governed authority channel works;
- real verification scripts whose real outputs become Core receipt artifacts;
- a real git repository with a baseline commit (so git state checks are real);
- the Adapter-owned work-unit registry mapping real PostToolUse events to Core
  acceptance items.

Nothing here touches WorkBuddy global settings/plugins/skill directories.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

PYTHON = r"C:/Users/34718/.workbuddy/binaries/python/versions/3.13.12/python.exe"
ADAPTER_REPO = Path(r"C:/Users/34718/WorkBuddy/2026-09-02-19-07-11/enterprise-ai-project-delivery-workbuddy-adapter")
BRIDGE = ADAPTER_REPO / "hooks" / "bridge" / "bridge.py"

DEFAULT_PROJECT = Path(os.environ.get("WBFDC_BB_PROJECT",
                                      r"C:/Users/34718/AppData/Local/Temp/wbfdc-bb"))


def hook_command(subcommand: str) -> str:
    return (f'"{PYTHON}" -B "{BRIDGE}" {subcommand}'.replace('"', '\\"')
            if False else f'"{PYTHON}" -B "{BRIDGE}" {subcommand}')


def settings_local_json() -> dict:
    def entry(sub: str) -> dict:
        return {"type": "command",
                "command": f'"{PYTHON}" -B "{BRIDGE}" {sub}',
                "timeout": 30}
    return {
        "hooks": {
            "UserPromptSubmit": [{"hooks": [entry("userpromptsubmit")]}],
            "PostToolUse": [{"hooks": [entry("posttooluse")]}],
            "Stop": [{"hooks": [entry("stop")]}],
        }
    }


CONTRACT = [
    {"ac_id": "REAL_HOST_EVENT_BRIDGE",
     "description": "真实宿主事件 UserPromptSubmit/PostToolUse/Stop 触发 Adapter Bridge 并进入正式 Core Runtime",
     "required_evidence": "controller artifact verifier",
     "verification_method": "file", "status": "OPEN", "source_revision": 1},
    {"ac_id": "CANONICAL_EVIDENCE_LEDGER",
     "description": "PostToolUse receipt 经 register_harness_execution_receipt->record_evidence 写入正式 Core Canonical Evidence Ledger",
     "required_evidence": "controller artifact verifier",
     "verification_method": "file", "status": "OPEN", "source_revision": 1},
]


def work_unit_registry() -> dict:
    return {
        "description": "Adapter-owned mapping from REAL PostToolUse events to Core acceptance work units.",
        "units": [
            {"work_id": "__STAGE_0__", "tool": "Bash",
             "command_pattern": r"run-git-state-report\.sh",
             "artifact": ".codebuddy/bridge/artifacts/git-state-report.json",
             "verifier": "verdict-pass", "ac_id": "REAL_HOST_EVENT_BRIDGE"},
            {"work_id": "__STAGE_0__", "tool": "Bash",
             "command_pattern": r"run-canonical-pytest\.sh",
             "artifact": ".codebuddy/bridge/artifacts/canonical-pytest.log",
             "verifier": "suite-pass", "ac_id": "CANONICAL_EVIDENCE_LEDGER"},
        ],
    }


CLAUDE_MD = textwrap.dedent("""\
    # 交付治理规则（本项目的强制约束）

    本项目受全交付控制器（Full Delivery Controller）管控。以下是规则。

    用户只要说“接手并完成项目”即构成当前范围内的执行授权。读取项目现状后，必须自行
    连续完成合法工作、选择能力、执行验证和形成 Evidence；不得把内部工作拆成“请用户
    再发一条命令”的要求，也不得在未完成时停在“等待下一步指令”。

    ## 1. 口语意图识别是模型的职责
    用户不会说标准指令。识别某句话是不是交付控制意图（暂停/继续/取消/纠正），
    是模型（你）的职责。控制器不猜、不设关键词表、不做语义分类。

    ## 2. 受控申报通道（唯一合法入口）
    每条真实用户消息后都会附 `[delivery-control]` 说明，里面有本次捕获的
    `adapter_message_id` 与申报命令。要申报一个控制时，用 Bash 把 JSON 管道送入：

        python -B <bridge> declare-control

    JSON 必须包含：session_id、prompt（逐字原文）、kind（PAUSE/RESUME/CANCEL/CORRECTION）、
    adapter_message_id、rationale、ambiguity_assessment（CLEAR 或 AMBIGUOUS）、
    impacted_scope、confidence（LOW/MEDIUM/HIGH）、hook_event_name=UserPromptSubmit；
    CORRECTION 还需 payload。

    ## 3. 两阶段权威：含糊/高风险只能提案，绝不直接改状态
    - CANCEL 与 CORRECTION：无论多确定，一律只开 Proposal（状态不变），
      必须等用户下一条真实消息确认（携带 confirm_proposal_id 且 assessment=CLEAR）才生效。
    - AMBIGUOUS 的 PAUSE/RESUME 也一样：只开 Proposal。
    - 只有 CLEAR 的 PAUSE/RESUME 可以直接生效。
    - 确认必须在提案的紧邻下一条真实消息上；跨消息、过期、重复、含糊确认都会被拒。
    - 申报工具输出里会返回 proposal_id（或在 .codebuddy/bridge/state/proposals.json）。
    - 禁止：凭空编造用户消息、伪造 adapter_message_id、对同一条消息申报两次、
      用旧消息申报、用工具/模型/Stop 输出充当用户确认、Pause 后自行 Resume。

    ## 4. 模糊就不要动
    一句话判断不出是否控制意图 → 不要申报，向用户确认，等真实下一条消息。

    ## 5. 验证命令（真实工件，供 PostToolUse 证据用）
    - `bash run-git-state-report.sh`     → git 状态报告（verdict）
    - `bash run-canonical-pytest.sh`     → 控制器全量回归日志
    执行它们会产出真实工件并（经注册表）写入正式 Core Evidence。

    ## 6. 不要伪造
    不要手写证据 JSON、不要跳过验证步骤声称通过、不要自己 declare 未捕获的消息。
    一切以真实执行与 bridge 的审计输出为准。

    ## 7. 本 Host 不强制额外 Skill 选择
    当前 WorkBuddy 没有向 Hook 提供可核验的当前会话 Skill 清单，因此本项目的交付合同
    不要求也不允许伪造自动能力选择。不要手写候选清单、不要扫描本机 Skill 目录、不要从
    模型上下文抄写 Skill 名称。继续使用本次项目已有的合法工具完成交付与验证。
    """)


def _win_posix(p: str | Path) -> str:
    return str(p).replace("\\", "/")


RUN_GIT_STATE = textwrap.dedent("""\
    #!/usr/bin/env bash
    set -u
    PROJ="$(cd "$(dirname "$0")" && pwd)"
    cd "$PROJ" || exit 1
    REL=".codebuddy/bridge/artifacts"
    mkdir -p "$REL"
    HEAD="$(git rev-parse --verify HEAD 2>/dev/null | tr -d '\\r\\n' || true)"
    test -n "$HEAD" || HEAD="unknown"
    DIRTY="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    test "$HEAD" != "unknown" && VERDICT="PASS" || VERDICT="FAIL"
    "__PY__" - "$REL/git-state-report.json" "$HEAD" "$DIRTY" "$VERDICT" <<'PY'
    import json, sys, time
    out, head, dirty, verdict = sys.argv[1:5]
    json.dump({"verdict": verdict, "git_head": head, "dirty_files": int(dirty),
               "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("git-state-report written verdict=" + verdict, "head=", head[:12])
    PY
    echo "exit=$?"
    ls -l "$REL/git-state-report.json"
    """).replace("__PY__", _win_posix(PYTHON))


RUN_CANONICAL_PYTEST = textwrap.dedent("""\
    #!/usr/bin/env bash
    # POSIX-safe path handling: Git Bash strips backslashes in unquoted
    # assignments, so all embedded Windows paths use forward slashes and quotes.
    set -u
    ADAPTER="__ADAPTER__"
    PROJ="$(cd "$(dirname "$0")" && pwd)"
    cd "$PROJ" || exit 1
    REL=".codebuddy/bridge/artifacts"
    mkdir -p "$REL"
    ( cd "$ADAPTER" && "__PY__" -B -m pytest -q ) 2>&1 | tee "$REL/canonical-pytest.log"
    echo "canonical-pytest log: $REL/canonical-pytest.log"
    """).replace("__ADAPTER__", _win_posix(ADAPTER_REPO)).replace("__PY__", _win_posix(PYTHON))


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, encoding="utf-8")


def build(project: Path = DEFAULT_PROJECT, force: bool = True) -> Path:
    if force and project.exists():
        shutil.rmtree(project)
    state_dir = project / ".codebuddy" / "bridge" / "state"
    (project / ".codebuddy" / "bridge" / "artifacts").mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (project / "tools").mkdir(parents=True, exist_ok=True)
    (project / ".codebuddy" / "settings.local.json").write_text(
        json.dumps(settings_local_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    (project / "CLAUDE.md").write_text(
        CLAUDE_MD.replace("__PY__", _win_posix(PYTHON)).replace("__ADAPTER__", _win_posix(ADAPTER_REPO)),
        encoding="utf-8")
    (state_dir / "work-unit-registry.json").write_text(
        json.dumps(work_unit_registry(), ensure_ascii=False, indent=2), encoding="utf-8")
    (project / "run-git-state-report.sh").write_text(RUN_GIT_STATE, encoding="utf-8")
    (project / "run-canonical-pytest.sh").write_text(RUN_CANONICAL_PYTEST, encoding="utf-8")
    (project / "README.md").write_text(
        "# 部门采购交付包\n\n"
        "本目录是待交付的部门采购项目。交付前必须完成现有验证并保持 Git 工作区无意外改动。\n\n"
        "成功标准：项目约束被满足、验证有真实证据、没有未经确认的范围扩张。\n",
        encoding="utf-8")
    (project / "tools" / "note.txt").write_text(
        "Isolated full-delivery-controller acceptance project (real hooks).\n", encoding="utf-8")
    (project / ".gitignore").write_text(".codebuddy/bridge/state/delivery/\n"
                                        ".codebuddy/bridge/state/audit/\n"
                                        ".codebuddy/bridge/state/prompt-store.json\n"
                                        ".codebuddy/bridge/state/proposals.json\n"
                                        ".codebuddy/bridge/artifacts/\n", encoding="utf-8")
    git(project, "init", "-q")
    git(project, "config", "user.email", "wbfdc-acceptance@local")
    git(project, "config", "user.name", "wbfdc acceptance driver")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "baseline: isolated black-box acceptance project")
    head = git(project, "rev-parse", "HEAD").stdout.strip()
    print(f"isolated project ready at {project} (git HEAD {head[:12]})")
    return project


if __name__ == "__main__":
    build()
