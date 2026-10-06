# CLI 参考（Reference）

> 全部命令通过 `uv run sai <子命令>` 调用。`--help` 看每个命令的参数。

## 情报采集

| 命令 | 说明 |
| --- | --- |
| `sai scan [--limit N] [--detail N]` | 扫官网通知列表（零 LLM）；`--detail` 补抓指定条目正文 |
| `sai identify [--limit N]` | 识别最新通知是否比赛（花 LLM，写卡片库） |
| `sai report` | 把比赛卡片渲染成 Markdown 报告（`/report` 同源） |

## 生成

| 命令 | 说明 |
| --- | --- |
| `sai generate --skill ppt-outline` | 生成参赛材料（AgentScope 循环；pptx 插件开着自动导出 .pptx） |
| `sai study-path` | 备考学习路径（联网搜索 + 引用校验） |

## 成本与会话

| 命令 | 说明 |
| --- | --- |
| `sai cost [--today] [--task X]` | LLM 花费账单（总量/按任务/按模型） |
| `sai sessions` | 最近任务会话列表（编号供 replay 用） |
| `sai replay <编号>` | 回放一次任务的完整轨迹（含每轮 token 与花费） |
| `sai memory list` / `sai memory clear` | 查看/清理识别结论缓存（改提示词后清） |

## 评测与守望

| 命令 | 说明 |
| --- | --- |
| `sai eval [--save]` | 31 条真实考卷考识别能力，与基线比对防退化（`--save` 建基线） |
| `sai watch` | 盯一次官网：识别 + 新比赛推送到已配置通道 + 截止警报 |
| `sai deadlines` | 未来 30 天截止列表（只读，不推送） |

## 模型与服务

| 命令 | 说明 |
| --- | --- |
| `sai model list` / `sai model use <档案>` | 查看/切换模型档案（写回 config.yaml） |
| `sai serve [--host H] [--port P]` | 启动 FastAPI 单端口服务（界面 + API） |

## 典型组合

```bash
# 日常盯梢（配了 cron 就是自动化，见 how-to/配置定时推送.md）
uv run sai watch

# 改了识别提示词/路由之后必跑（防退化）
uv run sai eval
uv run sai memory clear   # 必要时清缓存

# 看这个项目今天花了多少钱
uv run sai cost --today
```
