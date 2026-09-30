# ADR-001：Agent 层弃用框架，自研手写 harness

- **状态**：已接受（2026-09-30）
- **背景**：v1.3 曾定 AgentScope 2.0.8（锁版，Globex 同款）。开发者在实施前提出质疑："AgentScope 比较小众"，且真实目标是做出带上下文管理、记忆、成本控制、与 Claude 功能相当的 Agent。

## 决策

Agent 层**不引入任何第三方框架**，在 `application/harness/` 手写：ReAct loop、工具注册表（JSON Schema）、skill 加载器。v2 沿三条主线将其升级为 mini-harness：上下文管理、记忆、成本控制，辅以 trace/评测、权限门、子代理。

## 理由

1. **本项目的 agent 面极小**：走 agent loop 的只有材料生成与学习路径两个用例，各为一个循环挂 3-4 个工具；更难的识别/提取定为单次结构化调用。框架承载量趋近于零，而 loop 手写约 150-200 行。
2. **学习目标即 harness 本身**：上下文管理（= token 计量 + 阈值摘要）、记忆（= markdown 文件 + 注入）、成本控制（= usage 台账 + 预算闸门 + 模型路由）都是边界清晰的组件，框架恰好会把这层包成黑盒。
3. **候选框架尽调均不占优**（2026-09）：AgentScope 二梯队且三次破坏性重写；LangGraph 对单循环是牛刀；Pydantic AI 留作 v2 若需框架时的首选；Claude Agent SDK 官方 Python 版绑定 Anthropic 模型，与 DeepSeek 默认决策冲突。
4. **TS harness（deepseek-harness / claude-code）包装路线否决**：胶水层厚于省掉的代码；Python 领域工具跨语言撕裂；双运行时毁掉"10 分钟跑通"验收；自建集成无社区可救。
5. **复刻 Globex 的学习价值不受损**：要复刻的是四层、装配根、settings、端口这些架构纪律，与具体 agent 库无关。

## 后果

- 正面：零框架依赖风险与版本变动风险；逐行理解 agent 机制；技能可迁移到任何框架。
- 负面：harness 质量责任在自己——以循环 trace 日志 + v2 评测套件兜底；skill 加载器、结构化输出解析需自写（均为百行级）。
- 回退方案：端口隔离使 harness 局部化，v2 若 agent 面扩大，换 Pydantic AI 仅动 `application/harness/`。
