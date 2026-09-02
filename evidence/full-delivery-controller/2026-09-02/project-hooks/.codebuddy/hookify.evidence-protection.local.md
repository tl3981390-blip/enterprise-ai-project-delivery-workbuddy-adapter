---
name: delivery-evidence-protection
enabled: true
event: bash
pattern: rm\s+-rf|git\s+reset\s+--hard
action: warn
---

⚠️ 该命令可能破坏交付证据或 Git 状态。仅允许在明确授权范围内对临时文件执行。
