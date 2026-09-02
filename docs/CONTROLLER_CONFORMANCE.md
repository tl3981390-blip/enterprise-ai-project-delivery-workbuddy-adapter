# WorkBuddy Controller Conformance

总体状态：**CONTROLLER_NOT_CONNECTED**（完整 Human Authority 控制链未接入，也不得声称已接入）。

## 1. 判定标准（不变）

Adapter 只有在 WorkBuddy 自身提供并让 Adapter 实际使用以下原语时，才可以报告
`CONTROLLER_CONNECTED`：

1. 每个用户控制转换都带可信的 `session_id` + `conversation_id` + `message_id`；
2. 存在独立的宿主事件：用户暂停 / 恢复 / 取消 / 纠正；
3. 可持久化的项目级 Bridge State；
4. 可执行的完成拦截点。

本机真实审计结论（见 `AUDIT_WORKBUDDY_HOOKS.md`）：**第 1、2 条不成立**
（Hook 输入无 event_id，也无 conversation_id/message_id，且无上述独立事件）。
第 3、4 条成立。因此所有人工控制转换继续 fail-closed。

## 2. 已实现并测试的安全子集（本分支）

| 需求 | 实现 | 测试 |
| --- | --- | --- |
| A. 项目级显式开关 | 仅当 `<项目根>/.workbuddy/delivery-contract.json` 内容**精确等于** `{"adapter":"enterprise-ai-project-delivery-workbuddy-adapter","enabled":true}` 才激活；否则完全惰性 | test_project_gate_laziness.py |
| B. Bridge State | `<项目根>/.workbuddy/bridge/STATE.json` + `AUDIT.jsonl`；session 绑定/恢复/结束；episode 语义；回执去重；replay 摘要窗口 | test_bridge_state_sessions.py, test_replay_guard.py |
| C. Tool Evidence | 只有 `hook_event_name==PostToolUse` 且 payload 含真实 `tool_response` 才产生回执；模型自造 PASS 一律拒绝 | test_evidence_receipts.py |
| D. Stop / Evidence Gate | 项目启用 + 存在合法 Controller Session 时调用 Evidence Gate；无证据/证据不足 → `continue:false` 拦截完成；无合法 session → fail-closed 拦截 | test_stop_gate.py |
| E. Human Authority | USER_PAUSE / USER_RESUME / USER_CANCEL / USER_CORRECTION / Plan Approval / Requirement Change 全部 fail-closed；event_id ≠ message_id；文字「暂停/取消」不改任何状态 | test_human_authority.py |

隔离性：Bridge 不修改主 Core 仓库文件；不依赖作者电脑路径（见 test_isolation.py）。

## 3. 明确的禁止声明

- 本仓库不包含、不复制、不 fork 主 Core 的 Runtime / Evidence / Human Authority /
  MODULE 代码。
- `hooks/hooks.json` 只是候选清单，保持空数组，**绝不全局注册**。
- 未启用项目：不创建 Controller Session、不创建状态文件、不拦截 Stop、不影响普通对话。

## 4. 兼容的正式 Core（只读目标，永不 vendor）

| Field | Value |
| --- | --- |
| Core version | `3.0.6` |
| Tag | `v3.0.6` |
| Commit | `0937642afa0d488b20701c87e2ee3cd2a921cd2d` |
| Asset SHA-256 | `2512a954e1a73e3a6070318d7018ac6424d6904164db19e560f8ba9ec0cd4d5f` |

## 5. 未来可升级为 CONNECTED 的条件

WorkBuddy 提供以下任一演进并被真实会话实测后，本 Adapter 才可逐项放开：

1. Hook 输入携带可信 `conversation_id` + `message_id`；
2. 出现独立宿主用户控制事件（pause/resume/cancel/correction / plan approval /
   requirement change）；
3. 在真实 WorkBuddy 桌面会话中完成「注册 → 触发 → 拦截 → 放行」端到端实测，
   且 `probe_workbuddy.py` 报告所有检查通过。

在此之前，一切声称保持现状：`CONTROLLER_NOT_CONNECTED`。
