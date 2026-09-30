"""usage_report 用例：把台账+会话账本聚合成前端 Overview 面板的数据（M4）。

回答六问（对应截图的六张统计卡）：
    最近一段时间开了几次会话？发了多少条消息？花了多少 token？
    活跃了几天？哪个小时用得最凶？最常用哪个模型？
再附赠三样：逐日 token（画热力图）、按模型分组（Models 标签页）、
本周/上周对比（趣味文案）。

聚合全部在 Python 里做（数据和量级都小），仓储只管按条件取流水——
和 CostReport 同一个取舍：业务逻辑放用例层，才能用假仓储离线测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ...domain.entities import UsageEntry
from ...domain.ports import SessionArchivePort, UsageRepositoryPort

# 支持的时间范围（GET /api/usage/summary?range=...）
RANGES = ("all", "30d", "7d")


@dataclass
class DailyUsage:
    """一天的 token 总量（热力图的一个格子）。"""

    date: str   # "YYYY-MM-DD"
    tokens: int


@dataclass
class UsageSummary:
    """Overview 面板的完整数据包。"""

    range: str = "all"
    sessions: int = 0                     # 区间内开的会话数
    messages: int = 0                     # LLM 调用次数（一次调用 ≈ 一条消息）
    total_tokens: int = 0                 # 输入+输出 token 合计
    active_days: int = 0                  # 有用量的天数
    peak_hour: int | None = None          # 用量最大的小时（0-23）；无数据显示 None
    favorite_model: str | None = None     # token 花得最多的模型
    by_model: dict[str, int] = field(default_factory=dict)   # 模型 -> token 数
    daily: list[DailyUsage] = field(default_factory=list)    # 有用量的日子（热力图取数）
    this_week_tokens: int = 0             # 本周一 0 点至今
    last_week_tokens: int = 0             # 上周一整周
    week_ratio: float | None = None       # 本周/上周；上周为 0 时是 None（没法比）


class UsageReport:
    """聚合台账与会话账本，产出 Overview 数据包。"""

    def __init__(self, usage_repository: UsageRepositoryPort,
                 session_repository: SessionArchivePort):
        self.usage_repository = usage_repository
        self.session_repository = session_repository

    def execute(self, range_name: str = "all") -> UsageSummary:
        if range_name not in RANGES:
            raise ValueError(f"range 只支持 {'/'.join(RANGES)}，收到 {range_name!r}")

        now = datetime.now()
        since = None
        if range_name == "30d":
            since = now - timedelta(days=30)
        elif range_name == "7d":
            since = now - timedelta(days=7)

        entries = self.usage_repository.list_entries(since=since)

        summary = UsageSummary(range=range_name)
        tokens_by_day: dict[str, int] = {}
        tokens_by_hour: dict[int, int] = {}
        tokens_by_model: dict[str, int] = {}

        for entry in entries:
            total = entry.prompt_tokens + entry.completion_tokens
            summary.messages += 1
            summary.total_tokens += total
            tokens_by_model[entry.model] = tokens_by_model.get(entry.model, 0) + total
            if entry.created_at is not None:
                day_key = entry.created_at.strftime("%Y-%m-%d")
                tokens_by_day[day_key] = tokens_by_day.get(day_key, 0) + total
                hour = entry.created_at.hour
                tokens_by_hour[hour] = tokens_by_hour.get(hour, 0) + total

        summary.active_days = len(tokens_by_day)
        summary.daily = [
            DailyUsage(date=day, tokens=tokens)
            for day, tokens in sorted(tokens_by_day.items())
        ]
        summary.by_model = dict(
            sorted(tokens_by_model.items(), key=lambda kv: -kv[1])
        )
        if tokens_by_hour:
            summary.peak_hour = max(tokens_by_hour, key=lambda h: tokens_by_hour[h])
        if summary.by_model:
            summary.favorite_model = next(iter(summary.by_model))

        # 会话数：列表取回后按 started_at 过滤（数据量小，不值得为它加 SQL）
        since_for_sessions = since or datetime(1970, 1, 1)
        sessions = self.session_repository.list_sessions(limit=1000)
        summary.sessions = sum(
            1 for s in sessions
            if s.started_at is not None and s.started_at >= since_for_sessions
        )

        # 本周/上周对比（周一为一周起点）
        monday = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        last_monday = monday - timedelta(days=7)
        summary.this_week_tokens = sum(
            e.prompt_tokens + e.completion_tokens
            for e in entries if e.created_at and e.created_at >= monday
        )
        summary.last_week_tokens = sum(
            e.prompt_tokens + e.completion_tokens
            for e in entries if e.created_at and last_monday <= e.created_at < monday
        )
        if summary.last_week_tokens > 0:
            summary.week_ratio = summary.this_week_tokens / summary.last_week_tokens

        return summary


def fun_fact(summary: UsageSummary) -> str:
    """生成 Overview 底部那句趣味文案（对应截图的 "~4× more than Animal Farm"）。

    有上周数据比倍数；没有就换别的真实话术，绝不编数字。
    """
    if summary.week_ratio is not None:
        if summary.week_ratio >= 2:
            return f"本周的 token 用量是上周的 {summary.week_ratio:.1f} 倍。"
        if summary.week_ratio < 1:
            return f"本周的 token 用量只有上周的 {summary.week_ratio:.0%}，省得很稳。"
        return "本周的 token 用量和上周基本持平。"
    if summary.last_week_tokens == 0 and summary.this_week_tokens > 0:
        return "本周开始有用量了——账本记下了第一笔。"
    return "还没有可比的用量记录。跑一次识别或对话就有了。"
