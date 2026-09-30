# 更新日志

本项目的全部重要变更都记录在此文件中。
格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

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
