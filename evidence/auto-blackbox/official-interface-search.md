# 官方接口检索证据：WorkBuddy 可执行的项目级 Hook 自动化接口

日期：2026-09-02
分支：`enterprise-ai-project-delivery-workbuddy-adapter` @ `workbuddy-full-delivery-controller`
目的：在执行自动黑盒验收之前，穷尽 WorkBuddy 当前安装版本里「官方可执行的项目级 Hook runner /
测试驱动 / 会话自动化 / 事件回放接口」，并留下可复现的检索证据。

---

## 结论摘要

| # | 候选接口 | 是否存在 | 能否执行 Python bridge | 证据 |
|---|---------|---------|----------------------|------|
| 1 | Hookify 插件 | **否**（未安装、未启用、二进制内零引用） | 否 | 见 §1 |
| 2 | 专用 Hook runner / 测试驱动 CLI 参数 | **否** | — | 见 §2 |
| 3 | 官方 CLI 会话自动化（`@genie/agent-cli`） | **是** | **是（已实测跑通）** | 见 §3 |
| 4 | 项目级命令 Hook（`.codebuddy/settings.local.json`） | **是** | **是** | 见 §4 |

**最终结论：存在官方可执行接口（#3 + #4），因此不得写 `BLOCKED_BY_WORKBUDDY_CAPABILITY`，
必须使用它完成真实自动黑盒验收。**

---

## §1 Hookify：本安装中不存在

```bash
# 1.1 插件缓存目录不存在
test -d "C:/Users/34718/.workbuddy/plugins/cache/codebuddy-plugins-official/hookify"
# => NO

# 1.2 全局 settings 的 enabledPlugins 中没有 hookify
grep -c "hookify" "C:/Users/34718/.workbuddy/settings.json"
# => 0

# 1.3 CLI 引擎二进制内零引用
grep -o -i "hookify" ".../cli/dist/codebuddy.js" | wc -l
# => 0

# 1.4 宿主主包内零引用
grep -o -i "hookify" "D:/工作ai/WorkBuddy/resources/app.asar" | wc -l
# => 0
```

`enabledPlugins` 实际内容（节选）：`agent-browser`、`find-skills`、`frontend-design`、
`sheetagent`、`tabbat`、`tencent-docs-plugin`、`tencent-docx`、`tencent-pptx`、
`weixinpay`、`document-skills`、`playwright-cli`。**无 hookify。**

→ 上一轮依赖的 `.codebuddy/hookify.*.local.md` 在本安装中没有任何运行时会读取它，
因此它不构成可执行接口。已删除该占位文件，改走 §4 的宿主原生命令 Hook。

## §2 不存在专用 Hook runner / 测试驱动参数

```bash
grep -o -E "\"--?[a-zA-Z][a-zA-Z-]*hook[a-zA-Z-]*\"" ".../cli/dist/codebuddy.js" | sort -u
# => (空)
```

CLI 参数全集里不存在 `--hook-runner` / `--test-hook` / `--replay-hook` / `--emit-hook`
之类的专用驱动参数。**没有官方「直接投递一个伪造 hook 事件」的测试开关**——
这也符合预期：官方不会提供伪造宿主事件的入口。

可用的会话自动化参数（§3）是唯一的官方可执行路径。

## §3 官方 CLI 会话自动化接口（实测可用）

位置（随 WorkBuddy 安装一起分发，非第三方）：

```
D:\工作ai\WorkBuddy\resources\app.asar.unpacked\cli\bin\codebuddy
package name: @genie/agent-cli
codebuddy --version  =>  2.137.1
```

关键参数（来自 `codebuddy --help`）：

| 参数 | 作用 |
|------|------|
| `-p` / `--print` | 非交互式真实会话 |
| `--session-id <id>` | 锁定会话身份（可跨进程续接） |
| `-c` / `--continue` | 续接已有真实会话 |
| `-r` / `--resume` | 恢复指定会话 |
| `--output-format json\|stream-json` | 机器可读转录 |
| `--input-format stream-json` | 流式输入 |
| `--dangerously-skip-permissions` | 无人值守下允许真实工具执行 |
| `--debug hooks` | Hook 调试 |
| `--port <n>` | 本地服务端口（**必须显式指定**，见下） |

### §3.1 踩坑：默认端口与宿主冲突

CLI 启动时会绑定 `127.0.0.1` 上的一个本地服务；默认端口实测为 `61511`，
而该端口已被运行中的 `WorkBuddy.exe`（pid 22892，即宿主本身）占用：

```
Unhandled rejection Error: listen EADDRINUSE: address already in use 127.0.0.1:61511
```

宿主不能杀（会连同当前会话一起死），因此**必须显式 `--port <空闲端口>`**。
驱动里用 `bind(("127.0.0.1", 0))` 取 ephemeral 端口解决。

### §3.2 实测跑通

在隔离项目 `C:\Users\34718\AppData\Local\Temp\wbfdc-auto-blackbox` 中：

```
node codebuddy -p "reply with exactly: HOOK_SMOKE_OK" \
     --output-format json --dangerously-skip-permissions \
     --session-id wbfdc-smoke-4 --port 62311
```

- 退出码 `0`，模型真实回复 `HOOK_SMOKE_OK`
- **模型收到的消息里被宿主注入了 Hook 输出**：
  `<system-reminder data-role="hook">{"continue": true}</system-reminder>`
  → 证明 UserPromptSubmit Hook 被真实执行
- 隔离项目生成审计文件 `.codebuddy/bridge/state/audit/wbfdc-smoke-4.jsonl`：
  - `UserPromptSubmit` → `captured_verbatim`（`adapter_message_id` 已生成，`kind: null`）
  - `Stop` → 真实 Stop 事件进入 bridge

## §4 项目级命令 Hook（宿主原生，CLI 同样遵守）

声明文件（两个都被引擎读取）：

```
<project>/.codebuddy/settings.local.json
<project>/.codebuddy/settings.json
```

引擎侧证据（`cli/dist/codebuddy.js`）：

- `HookExecutor` 出现 6 次
- 事件名常量完整：`UserPromptSubmit` `PostToolUse` `PreToolUse` `Stop`
  `SessionStart` `SessionEnd` `PreCompact` `Notification` `SubagentStop`
- 读取的 settings 文件名常量：`.codebuddy/settings.json`、`.codebuddy/settings.local.json`
- Hook 输出契约支持 `additionalContext`：
  `eu.additionalContext && el.additionalContext.push(eu.additionalContext)`
- `matchesTool`：未声明 `matcher` 时匹配全部工具

→ CLI 会话与桌面会话走同一套引擎Hook 执行器，因此在 CLI 里驱动出的事件
**就是真实宿主事件**，不是模拟 payload。

---

## §5 由此确定的自动黑盒方案

1. 官方 CLI 驱动真实会话（`-p` + `--session-id` + `--continue` + `--port <free>`）
2. 隔离演示项目里声明官方项目级命令 Hook
3. 用户文本由驱动通过 CLI 真实投递 → 真实 `UserPromptSubmit`
4. 模型在会话中真实调用工具 → 真实 `PostToolUse` → Core receipt
5. 会话结束 → 真实 `Stop` → Core completion gate
6. 一切判定只读审计 + Core 状态，不人工书写结论

用户全程不参与、不手工发送任何「暂停 / 继续 / 取消 / 确认」文本。
