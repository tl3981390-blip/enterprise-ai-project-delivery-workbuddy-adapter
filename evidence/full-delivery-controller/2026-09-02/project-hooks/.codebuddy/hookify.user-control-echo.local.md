---
name: delivery-user-control-echo
enabled: true
event: prompt
pattern: 暂停交付|继续交付|取消交付|记录纠正：
action: warn
---

⚙️ Delivery Controller 收到明确的用户控制指令（暂停/继续/取消/纠正）。该指令将交由 Human Authority Controller 处理；模型不得自行暂停、继续、取消或纠正。
