# 交付治理规则（本项目的强制约束）

本项目受全交付控制器（Full Delivery Controller）管控。以下是规则。

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
- `bash run-skill-git-report.sh`     → 按已加载 skill 流程产出 skill git 报告
执行它们会产出真实工件并（经注册表）写入正式 Core Evidence。

## 6. 不要伪造
不要手写证据 JSON、不要跳过验证步骤声称通过、不要自己 declare 未捕获的消息。
一切以真实执行与 bridge 的审计输出为准。
