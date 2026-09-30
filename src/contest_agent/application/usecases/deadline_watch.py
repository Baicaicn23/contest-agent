"""deadline_watch 用例：截止日期守望（M4 差异化方向①）。

垂直场景最痛的一刀：比赛情报的终极灾难不是"不知道"，而是
"知道了但错过报名"。卡片里的 deadline 字段此前只是躺在库里——
守望哨兵让它活起来：T-7 / T-3 / T-1 / T-0 四档倒计时警报，
推送通道与 sai watch 共用。

四条规则（全部围绕"同一场比赛别重复吵、别漏吵"）：
1. **四档警报**：剩余天数恰好 7/3/1/0 时各提醒一次（提醒频率递增，
   越近越吵；非阈值日安静——没人想要每天被吵一次）；
2. **记忆去重**：提醒过的级别记进持久记忆（key=deadline:通知URL），
   同一档绝不提醒第二次；
3. **晚添加补发**：T-4 才被识别到的卡片（错过 T-7）按当前剩余天数
   立即补发一次，之后的 3/1/0 照常走档；
4. **过期停报**：已过期的卡片不再提醒，只在报表里计数。

与 WatchSite 的关系：WatchSite 管"出现了什么新比赛"（事件驱动），
本哨兵管"时间到了没有"（时间驱动）。sai watch 一轮同时跑两者。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from ...domain.entities import Competition
from ...domain.ports import CompetitionRepositoryPort, MemoryPort, PushPort
from .watch_site import push_via_channels

# 警报阈值（剩余天数）。想在更多节点提醒就往里加（如 14）
THRESHOLDS = (7, 3, 1, 0)


@dataclass
class DeadlineAlert:
    """一场临近截止的比赛 + 它的紧迫度。"""

    card: Competition
    remaining: int        # 距截止还有几天（0 = 今天截止）
    label: str            # 人话紧迫度，如 "🔴 今天截止"

    @property
    def url(self) -> str:
        return self.card.notice_url


@dataclass
class DeadlineReport:
    """一次守望的结果。"""

    alerts: list[DeadlineAlert] = field(default_factory=list)   # 本轮要推的警报
    expired: int = 0                                            # 已过期的卡片数（停报，仅计数）
    upcoming: list[DeadlineAlert] = field(default_factory=list) # 未来 30 天内的全部（列表视图用）
    push_results: list[dict] = field(default_factory=list)


def _label(remaining: int) -> str:
    """剩余天数 → 人话紧迫度。"""
    if remaining == 0:
        return "🔴 今天截止"
    if remaining == 1:
        return "🟠 明天截止（最后一天）"
    if remaining == 3:
        return "🟡 还剩 3 天"
    if remaining == 7:
        return "🔵 还剩 7 天"
    return f"⏳ 还剩 {remaining} 天"


class DeadlineSentinel:
    """截止日期守望哨兵。由装配根构建；sai watch 每轮调用一次 execute。"""

    def __init__(
        self,
        competition_repository: CompetitionRepositoryPort,
        memory: MemoryPort | None = None,
        pushers: list[PushPort] | None = None,
        today: date | None = None,
    ):
        self.competition_repository = competition_repository
        # 去重状态存持久记忆（M2 的 memories 表）：哨兵是无状态的，
        # "上次提醒到哪一档"必须活在数据库里而不是进程里
        self.memory = memory
        self.pushers = pushers or []
        # today 可注入：测试定格日期用；生产默认系统今天
        self.today = today or date.today()

    # ---------- 只读视图（sai deadlines / GET /api/deadlines 用） ----------

    def upcoming(self, within_days: int = 30) -> list[DeadlineAlert]:
        """列出未来 within_days 天内截止的比赛，按紧迫度升序。不推送、不写记忆。"""
        return self._scan(within_days=within_days).upcoming

    # ---------- 主流程 ----------

    def execute(self, push: bool = True) -> DeadlineReport:
        """守望一轮：扫描 → 判定警报 → 推送并记账。

        记账（去重）只在"至少一个通道送达"后发生：
        - 推送全挂 → 不记账，下一轮同档还会再试（警报不能因通道抽风永久丢）；
        - push=False（干跑预览）→ 永不记账，看了不消耗。
        部分通道成功按送达处理（内容已经到了能到的地方，重推会对该通道重复吵）。
        """
        report = self._scan()

        if report.alerts and push and self.pushers:
            title = (
                f"⏰ 截止提醒：{len(report.alerts)} 场比赛临近截止"
                if len(report.alerts) > 1
                else f"⏰ {report.alerts[0].label}：{report.alerts[0].card.name}"
            )
            lines = []
            for alert in sorted(report.alerts, key=lambda a: a.remaining):
                deadline_str = alert.card.deadline.strftime("%Y-%m-%d")
                lines.append(
                    f"- {alert.label}｜**{alert.card.name}**（{deadline_str}）\n"
                    f"  {alert.url}"
                )
            content = "\n".join(lines) + "\n\n—— contest-agent 截止守望"
            report.push_results = push_via_channels(self.pushers, title, content)

            if any(r["ok"] for r in report.push_results):
                for alert in report.alerts:
                    self._remember_alerted(alert)

        return report

    # ---------- 内部 ----------

    def _scan(self, within_days: int | None = None) -> DeadlineReport:
        """扫描全部卡片，按规则产出警报与列表。"""
        report = DeadlineReport()
        cards = self.competition_repository.list_all()

        for card in cards:
            if card.deadline is None:
                continue  # 没写截止日期的卡片没法守望（但识别提示词会尽量提取）
            # 兼容两种类型：库里存的是 datetime，测试/归档可能给 date
            deadline_day = (card.deadline.date()
                            if isinstance(card.deadline, datetime) else card.deadline)
            remaining = (deadline_day - self.today).days

            if remaining < 0:
                report.expired += 1       # 已过期：停报，仅计数
                continue

            alert = DeadlineAlert(card=card, remaining=remaining, label=_label(remaining))
            if within_days is None or remaining <= within_days:
                report.upcoming.append(alert)

            if self._should_alert(card, remaining):
                report.alerts.append(alert)

        report.upcoming.sort(key=lambda a: a.remaining)
        report.alerts.sort(key=lambda a: a.remaining)
        return report

    def _should_alert(self, card: Competition, remaining: int) -> bool:
        """警报判定（规则 1/2/3 都在这里）。"""
        last_level = None
        if self.memory is not None:
            cached = self.memory.recall(f"deadline:{card.notice_url}") or {}
            last_level = cached.get("last_level")

        if remaining in THRESHOLDS:
            # 规则 1：到档必提醒——除非这个档已经提醒过（记忆里 last_level 更严或相等）
            return last_level is None or remaining < last_level
        if remaining < THRESHOLDS[0] and last_level is None:
            # 规则 3：7 天内才进视野的卡（晚添加），从没提醒过 → 立即补发一次
            return True
        return False

    def _remember_alerted(self, alert: DeadlineAlert) -> None:
        """警报推出去后记账：这个级别已经吵过（规则 2 的去重依据）。"""
        if self.memory is None:
            return
        try:
            self.memory.remember(
                f"deadline:{alert.card.notice_url}",
                {"last_level": alert.remaining,
                 "label": alert.label,
                 "alerted_at": self.today.isoformat()},
            )
        except Exception:
            pass  # 记忆故障不影响推送（存档组件的老规矩）
