"""harness 层：技能加载（skills）+ AgentScope 接驳层（agent_factory）。

v1.5 起（ADR-002）：ReAct 循环由 AgentScope 框架驱动，本层不再手写循环；
手写版实现（loop/registry）见 git 历史 `8cd5fe5` 之前。
本层现在的职责：把框架的模型/工具箱与本项目的端口能力组装起来。
详见 docs/adr/ADR-002 与 Obsidian 讲解文档 14。
"""
