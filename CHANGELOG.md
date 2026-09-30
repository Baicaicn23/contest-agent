# 更新日志

本项目的全部重要变更都记录在此文件中。
格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased] — v2/M1 成本台账与上下文管理

### 新增

- **成本台账**：新表 `usage_records` 记录每次 LLM 调用的 token 与费用；
  `sai cost`（支持 `--task` / `--today` / `--date`）与 `GET /cost` 查询；
  能回答"识别 10 条通知花了多少钱"（实测 ¥0.0173/4 次）
- **预算闸门**：`budget_per_task_yuan`（config.yaml 或环境变量
  `BUDGET_PER_TASK_YUAN`）设单任务花费上限，超限熔断；已产生的
  调用与入库结果保留（熔断不是清算）
- **模型路由**：config.yaml 的 `routing` 表按任务指定模型档案
  （识别配便宜模型、生成配强模型），`sai model` 展示路由表，
  台账按模型分组可证
- **上下文管理**：agent 循环接入 AgentScope 内置压缩
  （`context.trigger_ratio`，超阈值自动把旧对话压成结构化摘要）；
  所有工具返回值统一截断（4000 字安全网）；离线测试验证自动压缩真实发生
- **HTTP 接口**：`GET /cost`（按任务/日期过滤的成本账单）

### 设计决策

- **ADR-003**：成本记账走"两条 LLM 通路各设卡口"——结构化调用在
  `OpenAiCompatLlm` 注入 `CostMeter`，agent 循环用 `MeteredChatModel`
  代理包住框架模型客户端（熔断前查 + 调用后记账，用例层零改动）；
  上下文压缩采用框架内置能力不自研（沿 ADR-002 原则），被否决选项
  与已知缺口（压缩摘要调用不入账）见 ADR

### 变更

- `IdentifyCompetitions.execute` 逐条捕获预算熔断，保留已完成结果
- `settings.py` 新增模型单价（`input_price_per_m`/`output_price_per_m`）、
  路由、预算、上下文四组配置；config.yaml 同步
- 熔断时序定稿：`precheck()` 在下一次调用发出前拦截；
  打穿预算的当前调用照常入账

### 测试

- 离线 84 项（M1 新增 22 + /cost 接口回归 3）+ live 4 项全绿
- 真实验收：识别 10 条通知花费可答；`BUDGET_PER_TASK_YUAN=0.001`
  真实熔断演示通过；live 备考路径 13 笔循环调用全部入账

## [0.1.0] - 2026-09-30

首个公开发布版本：完整的"盯官网 → 识别比赛 → 生成材料/备考路径"闭环。

### 新增

- **自动盯官网（P1）**：爬取学院官网通知公告，选择器全配置化，限速 ≥1.5s、
  失败重试、逐条容错；真实页面样本离线测试
- **比赛识别（P2）**：关键词粗筛 + DeepSeek 单次结构化调用；卡片带逐字原文
  证据防幻觉；多模型档案热切换（`sai model use`）
- **存储与报告（P3）**：SQLAlchemy 两表（notices 台账 / competitions 资产）、
  双层幂等防线（代码判重 + 唯一索引）、Markdown 情报报告、可换数据库连接串
- **材料生成（P4）**：AgentScope 2.0.8 驱动的 ReAct 循环；技能外置
  （skills/*.md）；内置 PPT 大纲 / 参赛计划书两个技能；工具轨迹透明播报
- **备考路径（P5）**：联网搜索（Bing→360 多引擎回退，无需密钥）+
  引用存在性校验（死链自动反馈重做），全部链接经过程序验证
- **FastAPI 接口（P6）**：`/health` `/scan` `/competitions` `/report`
  `/generate` `/study-path`；密钥缺失时 LLM 接口优雅降级 503
- **CLI**：`sai scan / identify / report / generate / study-path / model / serve`
- **工程配套**：pytest 58 项（联网验收单独标记）、GitHub Actions CI、
  逐阶段学习讲解文档与术语表、ADR-001/002 架构决策记录

### 设计决策

- DDD 洋葱四层 + 装配根：换爬虫/模型/数据库实现只动一个文件（已实测两次）
- 架构边界：识别/提取走单次结构化调用；材料生成走 agent 循环（ADR-001 → ADR-002 记录了从手写循环到 AgentScope 的完整选型闭环）
