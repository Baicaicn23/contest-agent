"""generate_report 用例：把库里的比赛卡片渲染成一份 Markdown 情报报告。

报告是 P3 的"人能看的出口"：数据库里的卡片是给程序用的，
报告是给张三周五下午看的——按截止日期排序、标好类型、附上原文证据，
一眼知道最近该干什么。
"""

from __future__ import annotations

from datetime import datetime

from ...domain.entities import Competition
from ...domain.ports import CompetitionRepositoryPort

# 类型代码 -> 人话（和 CLI 里的映射保持一致含义）
TYPE_NAMES = {"deliverable": "交付物型", "exam": "考试型", "unknown": "待定"}


def _format_deadline(deadline: datetime | None) -> str:
    """截止日期统一渲染；没写就是"通知内未写"。"""
    return deadline.strftime("%Y-%m-%d") if deadline else "通知内未写"


class GenerateReport:
    """从仓储读出全部比赛卡片，渲染 Markdown 报告。"""

    def __init__(self, repository: CompetitionRepositoryPort):
        # 依赖注入：只认识端口，文件库/内存库/将来的 PostgreSQL 都照用
        self.repository = repository

    def execute(self) -> str:
        """生成报告，返回 Markdown 文本（写文件是调用方的事）。"""
        cards = self.repository.list_all()

        if not cards:
            return (
                "# 🏆 比赛情报报告\n\n"
                "> 暂无已识别的比赛。先跑 `sai identify` 积累一些卡片再来。\n"
            )

        # 按类型计数，放进报告头
        counts: dict[str, int] = {}
        for card in cards:
            counts[card.type] = counts.get(card.type, 0) + 1
        summary = " ｜ ".join(
            f"{TYPE_NAMES.get(t, t)} {n} 场" for t, n in counts.items()
        )

        lines: list[str] = [
            "# 🏆 比赛情报报告",
            "",
            f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"
            f" ｜ 共 {len(cards)} 场比赛（{summary}）",
            "",
            "## 📅 比赛一览（按截止日期排序）",
            "",
            "| # | 比赛 | 类型 | 截止 | 通知来源 |",
            "| - | --- | --- | --- | --- |",
        ]

        for number, card in enumerate(cards, start=1):
            type_name = TYPE_NAMES.get(card.type, card.type)
            lines.append(
                f"| {number} | {card.name} | {type_name} "
                f"| {_format_deadline(card.deadline)} | [通知]({card.notice_url}) |"
            )

        lines += ["", "## 🔍 原文证据（人工复核用）", ""]

        # 证据逐条列出：LLM 的判断必须能对回原文，报告负责把这层关系摆出来
        for card in cards:
            lines += [
                f"### {card.name}",
                "",
                f"- 类型：{TYPE_NAMES.get(card.type, card.type)}"
                f"｜截止：{_format_deadline(card.deadline)}",
                f"- 来源：{card.notice_url}",
                "",
                f"> {card.evidence or '（无证据）'}",
                "",
            ]

        return "\n".join(lines)
