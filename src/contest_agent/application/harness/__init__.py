"""手写 harness 核心：ReAct 循环（loop）、工具注册表（registry）、技能加载（skills）。

v1.4 决策：不用任何第三方 Agent 框架，这一层就是学习内容本身。
P4 起正式服役：generate_material 用例由这台循环驱动。
详见 docs/adr/ADR-001 与 Obsidian 讲解文档 14（/Users/momo/obsidian/notes/水赛codex/）。
"""
