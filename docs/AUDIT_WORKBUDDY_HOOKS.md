# 本机真实 WorkBuddy Hook 审计报告

审计日期：2026-09-02（本机 `win32`，WorkBuddy 桌面版）。
方法：只读检查三类权威来源，全程不写任何 WorkBuddy 配置、不注册 Hook、不重启应用。

1. 实机配置快照：`C:\Users\34718\.workbuddy\settings.json`、`plugins\installed_plugins.json`
2. 官方本地文档：`D:\工作ai\WorkBuddy\resources\app.asar.unpacked\cli\dist\web-ui\docs\cn\cli\hooks.md`（及 hooks-guide.md）
3. 官方实现源码：`D:\工作ai\WorkBuddy\resources\app.asar.unpacked\cli\dist\codebuddy.js`（23.5 MB，本机安装版本的 Hook 引擎）
4. 官方插件 Hookify 的真实 Hook 脚本（stdin JSON 消费者）

---

## 1. 真实 Hook payload 字段

### 官方本地文档（hooks.md「Hook 输入」）

公共字段只有：

```jsonc
{ "session_id", "transcript_path", "cwd", "permission_mode", "hook_event_name" }
```

事件字段：`PostToolUse` → `tool_name / tool_input / tool_response`；
`UserPromptSubmit` → `prompt`；`SessionStart` → `source`；`SessionEnd` → `reason`；
`Stop` → `stop_hook_active`。

### 引擎源码（codebuddy.js，只读扫描，byte offset 9021141–9022400）

`convertToSdkInput(...)` 的构造代码逐事件展开字段：

```js
let eu = { hook_event_name, session_id, transcript_path, cwd,
           ...(hook_specific_output) };
case POST_TOOL_USE: return { ...eu, "PostToolUse", tool_name, tool_input, tool_response };
case USER_PROMPT_SUBMIT: return { ...eu, "UserPromptSubmit", prompt };
case SESSION_START: return { ...eu, "SessionStart", source };
case SESSION_END: return { ...eu, "SessionEnd", reason };
case STOP: return { ...eu, "Stop", stop_hook_active };
```

关键词命中数（同一 bundle）：

| 关键词 | 命中 | 结论 |
| --- | --- | --- |
| `hook_event_name` | 49 | payload 构造键存在 |
| `tool_response` | 18 | PostToolUse 携带真实工具结果 |
| `stop_hook_active` | 9 | Stop 输入字段存在 |
| `conversation_id` | 21 | 仅出现在 Galileo 遥测上报对象中，**从不进入 Hook 输入** |
| `"message_id"` | 1 | 唯一命中是 Agent Mail 工具提示收集函数（与此无关），**从不进入 Hook 输入** |
| `"event_id"` | 0 | **Hook 输入中不存在 event_id** |

> 结论：本机真实 Hook 输入**不含** `event_id`，也**不含**可信的 `conversation_id` / `message_id`。
> `conversation_id`/`message_id` 只存在于内部遥测/会话对象，Hook 消费不到。
> 因此「把 Hook event_id 当 message_id」在本机连发生的可能性都不存在——这是硬阻塞，
> 不是风格问题。

## 2. Stop 是否真的能阻断

**能。**证据：

- hooks.md：`Stop` 退出码 2 / `{"continue": false, "reason": ...}` ⇒「阻止停止，向
  CodeBuddy 显示消息并继续对话」；且「如果停止是由于用户中断而发生的，则不会运行」。
- 引擎 `parseHookOutput`（offset 9012338）：`"boolean"==typeof eA.continue` →
  `allowed=eA.continue`，对 `Stop/SubagentStop` 置 `continue:false` 时不设
  `preventContinuation`（即：Agent 继续干活，而不是直接终止）。这就是可执行、
  可被 `/goal`、ChannelApproval 等内置功能复用的同一机制。

局限：注册后需 `/hooks` 面板审核 + 会话启动快照才生效；本次未在桌面会话里做真实拦截
演练（见矩阵），但「机制存在且可阻断」为已真实验证。

## 3. PostToolUse 能否取得真实工具执行结果

**能。** `convertToSdkInput` 的 `POST_TOOL_USE` 分支把 `tool_response` 原样放进输入；
hooks.md 也给出 `tool_response` 示例。PostToolUse 在工具**成功完成后**触发，无法撤销
执行，但可以读取真实结果、追加上下文或用 `updatedToolOutput` 替换给模型的内容。
Bridge 只用 `tool_response` 的存在性生成回执，模型自造文本永远不生成回执。

## 4. SessionStart / SessionEnd 能否用于项目级持久化

**事件本身可用于锚定项目级生命周期，但路径解析必须谨慎。**
- `SessionStart` 有 `source`（startup/resume/clear/compact）；引擎内部构造（offset
  12000280）的 stdin 对象**未显式带 cwd**，hooks.md 的 SessionStart 示例同样无 cwd。
- `SessionEnd` 有 `reason`（clear/logout/prompt_input_exit/other），hooks.md 示例带 cwd。
- Hook 命令生成时引擎提供 `CODEBUDDY_PROJECT_DIR` 环境变量（hooks.md 明确）。

因此 Bridge 的项目根解析顺序固定为：`CODEBUDDY_PROJECT_DIR` → payload `cwd`；
解析不到启用项目就直接惰性放行，绝不猜测。

## 5. 本机配置快照（只读）

| 项目 | 值 |
| --- | --- |
| `settings.json` 存在 | true |
| `settings.json` 含 `hooks` 键 | **false（当前零 Hook 注册）** |
| hookify 在 enabledPlugins | **false** |
| adapter 插件在 enabledPlugins | false |
| hookify 官方市场插件存在 | true（`plugins/marketplaces/codebuddy-plugins-official/plugins/hookify/hooks/hooks.json`） |
| hookify 真实脚本 | stop.py / posttooluse.py / pretooluse.py / userpromptsubmit.py（读 stdin JSON，exit 0） |

## 6. 能力矩阵（四类分级）

| # | 能力项 | 分级 |
| --- | --- | --- |
| 1 | Hook 输入为 stdin JSON，公共字段 `hook_event_name/session_id/transcript_path/cwd(/permission_mode)` | 已真实验证 |
| 2 | Hook 输入含 host `event_id` | BLOCKED_BY_WORKBUDDY_CAPABILITY（引擎 0 命中） |
| 3 | Hook 输入含可信 `conversation_id`+`message_id` 供用户控制 | BLOCKED_BY_WORKBUDDY_CAPABILITY |
| 4 | 存在 USER_PAUSE/USER_RESUME/USER_CANCEL/USER_CORRECTION 独立宿主事件 | BLOCKED_BY_WORKBUDDY_CAPABILITY |
| 5 | Stop 机制可阻断完成 | 已真实验证 |
| 6 | 桌面真实会话内完成「注册→Stop 拦截」端到端演练 | PENDING_EXTERNAL_VALIDATION（需面板审核/重启，本任务禁用） |
| 7 | PostToolUse 携带真实 `tool_response` | 已真实验证 |
| 8 | SessionStart/SessionEnd 可锚定项目级持久化 | 已真实验证（cwd 缺失场景已用 CODEBUDDY_PROJECT_DIR 兜底） |
| 9 | 当前 WorkBuddy home 无任何 Hook 注册 | 已真实验证 |
| 10 | 官方 hookify 插件为真实 stdin JSON 消费者 | 已真实验证 |
| 11 | Bridge 入口在未启用项目完全惰性 | 仅静态检查（自动化测试执行于本机合成 payload） |
| 12 | 完整 Human Authority 控制链已连接 | BLOCKED_BY_WORKBUDDY_CAPABILITY ⇒ 状态保持 CONTROLLER_NOT_CONNECTED |

## 7. 诚实边界

- 「仅静态检查」指：逻辑已在本机跑自动化测试，但未在真实 WorkBuddy 桌面会话里由
  宿主引擎驱动这些入口做过端到端验证。
- 「PENDING_EXTERNAL_VALIDATION」指：机制存在且证据充分，但一次真实桌面运行演练
  需要注册 Hook（改项目级 settings + `/hooks` 面板审核 + 重启/新会话快照），在
  本任务规则下不能执行。
- 「BLOCKED_BY_WORKBUDDY_CAPABILITY」指：宿主当前根本不提供该能力（字段/事件缺失），
  与是否愿意安装无关。
