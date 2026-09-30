"""watch_site 用例：盯一次官网，发现新比赛就推送（M3 定时推送的核心）。

流程：跑一遍识别（幂等 + 记忆缓存让重复跑很便宜）→ 对比"本次新入库
的卡片"→ 有新面孔就组装一条摘要，推给所有已启用的通道。

它本身不管定时——"每 30 分钟跑一次"交给 cron/launchd/`--loop` 循环。
用例只负责"盯一次"，单次职责简单才好测、好排错（这也是它没起名
叫 daemon 的原因：守护进程的活交给操作系统的调度器）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...domain.ports import PushPort
from .identify_competitions import IdentifyCompetitions


@dataclass
class WatchResult:
    """一次盯梢的结果。"""

    new_cards: list = field(default_factory=list)   # 本次新入库的比赛卡片
    push_results: list[dict] = field(default_factory=list)
    # 每个通道的推送结果：[{"channel": "webhook", "ok": True}, ...]


def _format_digest(new_cards: list) -> tuple[str, str]:
    """把新卡片组装成 (标题, 正文)。纯文本 + Markdown，各通道通用。"""
    if not new_cards:
        return "", ""
    title = f"🔔 发现 {len(new_cards)} 场新比赛"
    lines = []
    for card in new_cards:
        deadline = card.deadline.strftime("%Y-%m-%d") if card.deadline else "见通知"
        type_names = {"deliverable": "交付物型", "exam": "考试型"}
        type_name = type_names.get(card.type, card.type)
        lines.append(
            f"- **{card.name}**（{type_name}，截止 {deadline}）\n"
            f"  {card.notice_url}"
        )
    content = "\n".join(lines) + "\n\n—— contest-agent 自动盯梢"
    return title, content


def push_via_channels(pushers: list[PushPort], title: str, content: str) -> list[dict]:
    """把一条消息推给所有已启用通道，返回逐通道结果（M3/M4 共用）。

    降级原则：一个通道挂了不拖累其他通道；失败结果如实上报给调用方。
    WatchSite（新比赛）和 DeadlineSentinel（截止警报）共用这一份。
    """
    results = []
    for pusher in pushers:
        try:
            pusher.send(title, content)
            results.append({"channel": pusher.channel_name, "ok": True})
        except Exception as error:
            results.append(
                {"channel": pusher.channel_name, "ok": False, "error": str(error)}
            )
    return results


class WatchSite:
    """盯一次官网：识别 -> 找新面孔 -> 推送（有配置的通道全推一遍）。"""

    def __init__(self, identify: IdentifyCompetitions, pushers: list[PushPort] | None = None):
        self.identify = identify
        # pushers：所有启用的推送通道。空列表 = 只识别不外推（终端里看结果）
        self.pushers = pushers or []

    def execute(self, limit: int = 10, push: bool = True) -> WatchResult:
        """盯一次。push=False 时只识别不推送（干跑/调试用）。"""
        outcomes = self.identify.execute(limit=limit)
        result = WatchResult(new_cards=list(self.identify.new_cards))

        if not push or not result.new_cards:
            return result

        title, content = _format_digest(result.new_cards)
        # 逐通道推送；一个通道挂了不拖累其他通道（降级原则：
        # webhook 挂了，邮件和文件照发），失败结果照样汇报给调用方
        result.push_results = push_via_channels(self.pushers, title, content)
        return result
