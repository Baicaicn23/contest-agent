# 更新日志

本项目的全部重要变更都记录在此文件中。
格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased] — v2/M4 Web 界面（复刻 Claude Desktop）

### 新增

- **Web 界面**（frontend/，React 18 + Vite + 手写 CSS 设计令牌，中文本地化）：
  - **工作台**：问候语 + Overview 卡（会话/消息/总 token/活跃天数/高峰时段/
    常用模型六统计 + 18 周热力图 + 模型用量表 + 周对比趣味文案）——
    全部来自新接口 `GET /api/usage/summary` 的真实台账聚合
  - **情报站**：serif 大字问候 + 居中输入卡 + 点子列表（识别/生成/备考/账单一键执行）
  - **会话视图**：自由对话（SSE 逐字流式）+ 历史任务轨迹回放
    （M2 存档事件 → 右气泡/助手正文/工具折叠块；chat 会话可续聊）
  - **Settings**：亮暗主题与字号真切换（CSS 变量 + localStorage）；
    切模型档案、改预算上限（按行替换写回 config.yaml）；路由/权限/推送只读；
    其余分区视觉占位
  - **/ 命令面板**：/识别 /扫描 /生成 /备考 /账单 /报告
- **后端**：`GET /api/usage/summary`（UsageReport 聚合用例）、
  `POST /api/chat`（SSE 逐 token，人设注入实时数据 + 最近 6 轮上下文，
  花费照常入台账）、`GET /api/config`（脱敏）、`POST /api/config/model|budget`、
  `POST /identify`（P6 缺项补全）、FastAPI 托管 frontend/dist（sai serve 单端口）
- **新端口**：ChatStreamPort（能力十：流式自由对话）

### 变更

- settings.set_budget：预算按行替换写回 config.yaml（保注释），env 覆盖依旧优先
- 内存库 StaticPool 关闭跨线程检查（SSE 流式响应的工作线程需要）

### 测试

- 离线 133 项（M4 新增 16）+ live 4 项全绿
- 浏览器真实验收（对照五张 Claude Desktop 原图）：三视图、Settings 弹窗、
  用户菜单、暗色主题切换、Overview 真实数据、会话轨迹回放、
  chat 逐字流式（人设注入的实时卡片数正确）、/账单命令执行

## [Unreleased] — v2/M3 定时推送 + 研究分身 + 权限门

### 新增

- **定时推送**：`sai watch` 盯一次官网（识别与 `sai identify` 完全同款，
  幂等+记忆让反复跑几乎零成本），发现新比赛推送到所有已启用通道；
  三通道实现 PushPort——webhook（POST JSON，钉钉/企微/Server酱通用）、
  邮件（SMTP，密码走 `SMTP_PASSWORD`）、本地文件（Markdown 落盘，默认开启）；
  定时交给 cron/launchd（README 附 crontab 一行），`--loop` 可临时值守；
  单通道故障不拖累其他通道
- **研究分身（子代理）**：study-path 新增 `research_digest` 工具——分身内部
  搜索前 3 条、精读前 2 页、一次结构化调用压缩成"概述/要点/有用网址"摘要，
  主循环只收千字摘要；网址铁律照抄材料（P5 引用校验同源）；分身与主循环
  共用同一个计价器和会话记录（花费合并算账、轨迹同份存档）
- **权限门**：config.yaml `permissions` 两个名单——`confirm_tools`
  （交互模式执行前 y/N 确认）、`unattended_deny_tools`（无人值守一律拒绝，
  理由回给模型）；拒绝理由进会话轨迹；对照 pi"沙箱学派"的取舍已记录
  （工具自有且有界，权限门够用；引入 shell 类工具时再评估沙箱）

### 变更

- 识别用例补 `new_cards` 清单（推送只推本次新入库的卡片）
- 工具注册链扩为"截断 → 权限门 → 会话记录"，权限门的拒绝也留档可回放
- config.yaml 新增 `push` / `permissions` 配置段（默认零行为变化）

### 测试

- 离线 117 项（M3 新增 18）+ live 4 项全绿
- 真实验收：本地 HTTP 收包器验证 webhook 推送闭环（JSON 全字段正确）、
  file 通道同秒防覆盖落盘、digest 有界且网址全来自材料、
  确认门/禁用门按名单生效

## [Unreleased] — v2/M2 记忆 + 会话存档 + 评测套件

### 新增

- **持久记忆**：memories 结论缓存——识别过的通知（比赛与否都记）直接
  命中、跳过 LLM；正文指纹防过期（内容变了自动重判）；
  `sai memory list/clear`。验收：二次扫描 0 次 LLM 调用
- **会话存档**：agent_sessions / session_events 两表 +
  SessionArchivePort（借鉴 pi 会话后端接口化思想）；模型调用、压缩、
  工具调用、逐条结果全埋点；成本台账按 session_id 归集到任务；
  `sai sessions` / `sai replay 编号` / `GET /sessions(/{id})`
- **评测套件**：31 条真实历史通知考卷（19 比赛 / 12 杂事，人工标注，
  进 git 作为契约）；准确率/精确率/召回/F1 + 比赛名称/截止日期命中；
  `sai eval --save` 建基线，之后每次自动回归比对（阈值 5 个百分点，
  判翻的题逐条点名）。**新纪律：改识别提示词/粗筛词表/模型路由后必跑**
- **评测考卷**：`tests/fixtures/eval_identify.json`（2019-2026 七年
  真实通知，可自行按格式扩充）

### 变更

- usage_records 台账新增 session_id 列（老库幂等就地迁移——账本含真实
  花费，不删库重建）；`SessionSummary` 带 llm_calls，显示区分"¥0（没调用）"
  与"费用未知（调了没配单价）"
- 识别用例：粗筛后查记忆、LLM 后写结论；ScanOutcome 带 from_memory 标记，
  CLI 播报"记忆命中省下 N 次调用"

### 测试

- 离线 99 项（M2 新增 15）+ live 4 项全绿
- 真实验收：二次扫描 0 调用；`sai replay` 回放完整轨迹（含每轮 token
  与总花费）；`sai eval` 两轮真跑 100% 准确率，基线闭环 PASS

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
