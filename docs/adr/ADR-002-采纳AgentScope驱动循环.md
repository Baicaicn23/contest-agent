# ADR-002：Agent 层循环采纳 AgentScope（部分推翻 ADR-001）

- **状态**：已接受（2026-09-30），推翻 ADR-001 中"自研手写循环"的结论；ADR-001 其余结论（端口架构、TS harness 不作基座、借鉴思想）继续有效
- **背景**：P4 按手写路线完成并通过验收（loop.py/registry.py，真实生成材料可用）。随后开发者重新评估框架价值（期间对照研究了 110k star 的 pi harness 项目），明确表达："把 Agent 部分全部换成 AgentScope，不要争"。项目所有者对维护手写循环缺乏信心与意愿——这是采用框架的决定性理由：**工具没有对错，用的人信不过的工具就是错的工具**。

## 决策

Agent 层循环采纳 `agentscope==2.0.8`（钉版）。移除自研的 `loop.py`、`registry.py`、`ToolCall`/`LlmReply` 实体和 `chat_with_tools` 接口；保留技能外置（skills/*.md）、三个工具函数、全部端口与业务层。新增 `harness/agent_factory.py` 作为框架接驳层。

## 迁移实录（半天，验证了 ADR-001 的回退方案）

| 自研实现 | AgentScope 对应物 |
| --- | --- |
| `loop.py` 的消息协议与轮转 | `Agent.reply()`（异步）+ `ReActConfig(max_iters)` |
| `registry.py` 的工具三要素 | `Toolkit.add_tool(FunctionTool(func=...))`——**schema 从 docstring 和类型标注自动生成**，我们写好的中文注释直接变成模型说明书 |
| 自研错误回传 | 框架的工具响应机制 |
| `save_material` 的硬约束 | 原样保留（框架权限系统之外的代码级防线） |

迁移中踩到的框架细节（已解决并记录在 `agent_factory.py` 注释）：① `Toolkit.add_tool`/`get_tool_schemas` 是异步方法；② 框架自带权限系统，未授权工具会挂起等确认——CLI 无人值守场景给每个工具显式挂 `PermissionDecision(ALLOW)`，硬约束仍由函数自身把守；③ `Msg.content` 必须是块列表（TextBlock）而非字符串。

## 理由

1. **所有者决策权**：开发者对长期维护手写循环信心不足，这个理由本身足够；
2. **实测适配**：AgentScope 2.0.8 冒烟 + 真实验收全过——ReAct 循环、自动 schema、DeepSeek 专用客户端、权限系统、结构化输出接口（`reply(structured_schema=pydantic模型)`，v2 可用）；
3. **迁移成本实测为半天**：业务层与工具函数零改动，验证了端口架构的回退承诺；
4. **框架白送的能力**：权限系统、上下文配置（ContextConfig）、状态管理——恰好是 v2 三条主线需要的地基。

## 后果

- 正面：循环由框架团队维护；白得权限/状态/结构化输出等框架能力；与国内 AgentScope 生态接轨。
- 负面：循环黑盒化（调试依赖框架文档与源码）；钉版 2.0.8 有上游版本变动风险；P4 手写版的教学文档随之改写（旧版在 git 历史与讲解文档变更注记中保留）。
- 回退方案：ADR-001 的手写实现在 git 历史（`8cd5fe5` 及之前），端口隔离保证随时可切回。
