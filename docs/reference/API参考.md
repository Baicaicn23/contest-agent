# API 参考（Reference）

> 全部 HTTP 端点。基础地址：`http://127.0.0.1:8000`（`uv run sai serve`）。
> 密钥缺失的 LLM 接口返回 503 + 配置指引，而不是整个服务不可用。

## 健康与核心任务

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 探活：`{status, version, active_model}` |
| POST | `/scan` | 扫官网通知列表（零 LLM）。body: `{limit, detail?}` |
| POST | `/identify` | 识别最新通知是否比赛（花 LLM）。body: `{limit}` |
| GET | `/competitions` | 比赛卡片列表 |
| GET | `/report` | 比赛情报 Markdown 报告 |
| POST | `/generate` | 为比赛生成参赛材料（30-90s，可导出 .pptx）。body: `{skill, competition?}` |
| POST | `/study-path` | 备考学习路径（联网搜索+引用校验）。body: `{competition?}` |
| GET | `/cost` | LLM 花费账单。query: `?today=true` / `?task=` / `?date=` |

## 聊天（SSE 流式）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/chat` | 聊天 agent（工具循环）。body: `{message, session_id?}`，SSE 帧：`session → token* → tool* → done` |
| POST | `/api/chat/close` | 关闭聊天会话。body: `{session_id}` |

## 会话与统计

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/sessions?limit=` | 最近会话概要（含 status/prompt_tokens/project_key） |
| GET | `/sessions/{id}` | 会话完整轨迹（回放用） |
| GET | `/api/usage/summary?range=` | 用量聚合（all/7d…）：总量/按任务/按模型/每日 |

## 工作台面板

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/deadlines` | 临近截止（30 天窗口 + 紧迫度分级） |
| GET | `/api/projects` · POST | 项目列表 / 手动新建 |
| POST | `/api/projects/bind` | 会话归属项目 `{session_id, project_key}` |
| DELETE | `/api/projects/{key}` | 删除手动项目（解绑会话不删会话） |
| GET | `/api/search?q=` | 全局搜索（会话/卡片/通知） |
| GET | `/api/notifications` | 紧急截止 + 近 24h 完成数 |
| GET | `/api/git/branch` | 当前 git 分支 |

## 配置（真实写回 config.yaml）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/config` | 脱敏配置视图（前端 Settings 数据源） |
| POST | `/api/config/model` | 切模型档案 `{name}` |
| POST | `/api/config/budget` | 预算 `{yuan}`（null 不限） |
| POST | `/api/config/access` | 完全访问总闸 `{full}`（兼容旧前端） |
| POST | `/api/config/permission-mode` | 三档权限 `{mode: readonly/confirm/full}` |

## 插件 / 技能 / 文件 / 终端

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/plugins` · POST `/api/plugins/{id}/toggle` | 能力插件清单与开关 |
| GET | `/api/skills` | skills/ 目录清单 |
| GET | `/api/files` · `/api/files/content?name=` | output/ 文件清单与预览（前 2000 字） |
| GET | `/api/tree` | output/ 递归树（限深 6） |
| POST | `/api/upload` | 上传附件到 output/uploads/（multipart，≤20MB，防穿越） |
| POST | `/api/terminal` | 项目根执行命令 `{command}`（30s 超时，输出截断 10KB） |

## 前端

`GET /` 及 `/chat` `/stats` `/deadlines` `/plugins` `/settings` ——
Next.js 静态导出产物，由 FastAPI StaticFiles 托管（单端口）。
