# 项目级启用与注册指南（REGISTRATION）

> 目标：让「一个项目」显式、可审计地启用 Bridge 的安全子集，同时保证其他项目、
> 全局 WorkBuddy 与主 Core 仓库零改动。

## 0. 铁律（违反即失败）

- 不得把 `hooks/hooks.json` 或任何 Hook 注册进 WorkBuddy **全局** settings。
- 不得修改 `~/.workbuddy/settings.json`、`enabledPlugins`、`installed_plugins.json`。
- 不得修改主 Core 仓库、`v3.0.6` tag、Release Asset 或 GitHub Release。
- 未启用项目必须完全惰性：无状态文件、无 Controller Session、无 Stop 拦截。

## 1. 把 Adapter 放进目标项目（推荐，机器无关）

把本仓库源码复制到目标项目根下（路径由 `$CODEBUDDY_PROJECT_DIR` 引用，不写死）：

```text
<project>/
  .workbuddy/
    delivery-bridge/          # 本仓库的 src/ 内容（复制而非子模块也可，随项目走）
      controller_contract.py
      project_gate.py
      bridge_state.py
      evidence.py
      stop_gate.py
      human_authority.py
      hooks/
        session_start.py
        session_end.py
        post_tool_use.py
        stop.py
```

## 2. 显式开启（A：项目级开关）

创建 `<project>/.workbuddy/delivery-contract.json`，内容必须**精确等于**：

```json
{
  "adapter": "enterprise-ai-project-delivery-workbuddy-adapter",
  "enabled": true
}
```

多一个键、少一个键、`enabled:false`、换了 adapter 名 → Bridge 一律保持惰性。

## 3. 项目级注册 Hook（只对本项目生效）

创建 `<project>/.codebuddy/settings.local.json`（项目本地、不提交）并加入：

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command",
        "command": "python3 \"$CODEBUDDY_PROJECT_DIR\"/.workbuddy/delivery-bridge/hooks/session_start.py" } ] }
    ],
    "PostToolUse": [
      { "matcher": "*", "hooks": [ { "type": "command",
        "command": "python3 \"$CODEBUDDY_PROJECT_DIR\"/.workbuddy/delivery-bridge/hooks/post_tool_use.py" } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command",
        "command": "python3 \"$CODEBUDDY_PROJECT_DIR\"/.workbuddy/delivery-bridge/hooks/stop.py" } ] }
    ]
  }
}
```

然后按官方机制在 `/hooks` 面板审核生效（引擎在会话启动时捕获 Hook 快照；外部文件修改
需审核后才应用）。桌面版是否需要重启以重建快照属外部验证项，见能力矩阵。

> 三个入口脚本自身就是惰性守卫：即使被注册到未启用项目，也会直接 `{"continue":true}`
> 退出，不建任何文件、不拦 Stop。

## 4. 预期行为（D：Evidence Gate）

- SessionStart 绑定 `session_id` 到 `<project>/.workbuddy/bridge/STATE.json`。
- PostToolUse 只在带真实 `tool_response` 时写入一条回执（同一 episode 内重复事件被拒）。
- 当 Agent 想「完成」时 Stop 入口执行 Evidence Gate：
  - 无 Controller Session / 状态损坏 → 拦截；
  - 证据 < 策略阈值（默认 ≥1 条真实回执）→ `{"continue": false, "reason": ...}` 拦截，
    reason 注入对话让 Agent 继续补齐；
  - 证据足够 → `{"continue": true}` 放行。

## 5. 现在仍不可用（E：Human Authority）

暂停/恢复/取消/纠正/计划批准/需求变更：本机 Hook 输入无 `conversation_id`/`message_id`，
也无独立宿主事件（审计证据见 `AUDIT_WORKBUDDY_HOOKS.md`）。这些操作一律 fail-closed，
任何自然语言「暂停/取消」都不会改变 Runtime 状态。
