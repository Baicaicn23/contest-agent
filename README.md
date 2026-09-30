# 水赛 Agent 助手（contest_agent）

自动盯学院官网通知 → LLM 识别比赛 → 提取结构化比赛卡片 → 交付物型按 Skill 生成材料（PPT 大纲/计划书/稿子）、考试型生成强制真实引用的学习路径。

架构：DDD 洋葱四层 + composition 装配根 + settings 环境优先配置，Agent 层为**自研手写 harness**（无第三方框架，见 [docs/adr/ADR-001](docs/adr/ADR-001-agent层自研手写harness.md)）。完整规划见 [docs/开发文档-v1.md](docs/开发文档-v1.md)，逐阶段学习讲解见 [讲解文档/](讲解文档/)。

## 快速开始

```bash
uv sync                          # 安装依赖（自动创建 .venv）
cp .env.example .env             # 填入 DEEPSEEK_API_KEY
uv run sai --help                # CLI 可用
uv run sai serve                 # 启动 FastAPI，默认 127.0.0.1:8000
curl http://127.0.0.1:8000/health   # {"status":"ok",...}
uv run pytest                    # 跑测试
```

## 目录

```
src/contest_agent/
├── domain/            # 实体 + 端口（洋葱最内层，零外部依赖）
├── application/       # 用例 + 手写 harness + 工具构建器
├── infrastructure/    # 爬虫 / LLM / 存储 / 搜索（实现 domain 端口）
├── presentation/      # FastAPI server + sai CLI 薄壳
├── composition.py     # 装配根：唯一知道具体实现的地方
└── settings.py        # 环境优先配置
```

## 路线

P0 初始化 ✅ → P1 爬虫 → P2 识别提取 → P3 存储 → P4 手写 harness → P5 学习路径 → P6 发布；v2：上下文管理 / 记忆 / 成本控制 / 评测套件。
