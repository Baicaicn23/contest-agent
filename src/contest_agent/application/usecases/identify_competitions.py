"""identify_competitions 用例：把一批通知变成"比赛卡片 + 判断理由"（P2 核心）。

每条通知的处理流程：
    1. 关键词粗筛：没沾比赛词的直接跳过（零成本挡掉大部分杂事）；
    2. 粗筛命中但没有正文 -> 补抓详情（截止日期等信息藏在正文里）；
    3. 调 LLM 做单次结构化调用，产出 JSON 卡片；
    4. is_competition=true 就地组装 Competition 实体；false 记下理由。

架构边界（开发文档 §3）：识别/提取走单次结构化调用，不走 agent 循环——
一问一答就能完成的事，不需要让模型反复决策。
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.entities import Competition, Notice, parse_date
from ...domain.ports import LlmPort, NoticeSourcePort
from ..keyword_filter import keyword_hit
from ..prompts import CARD_SCHEMA, IDENTIFY_SYSTEM_PROMPT

# 发给 LLM 的正文上限（字符）。再长的通知，开头 6000 字也足够判断；
# 截断同时控制了 token 成本，避免长通知把上下文窗口顶爆
MAX_CONTENT_CHARS = 6000


@dataclass
class ScanOutcome:
    """一条通知的识别结果：是否比赛、卡片（如是）、给人看的理由。"""

    notice: Notice
    is_competition: bool
    competition: Competition | None
    reason: str           # 人能读的判断理由（粗筛挡下 / LLM 的判断依据）
    llm_called: bool = False  # 这条有没有真的动用 LLM（被粗筛挡下的为 False）


class IdentifyCompetitions:
    """识别比赛：扫描 -> 粗筛 -> 补详情 -> LLM 识别 -> 卡片。"""

    def __init__(self, source: NoticeSourcePort, llm: LlmPort):
        # 依赖注入：爬虫和 LLM 都从外面递进来，本类只认识端口接口
        self.source = source
        self.llm = llm

    def execute(self, limit: int = 5) -> list[ScanOutcome]:
        """扫描最新 limit 条通知并逐条识别。"""
        notices = self.source.list_notices(limit=limit)
        return [self._identify_one(notice) for notice in notices]

    def _identify_one(self, notice: Notice) -> ScanOutcome:
        # 第 1 步：关键词粗筛（只看标题和已有内容，零成本）
        text = f"{notice.title}\n{notice.content}"
        if keyword_hit(text) is None:
            return ScanOutcome(
                notice=notice,
                is_competition=False,
                competition=None,
                reason="关键词粗筛未命中，未调用 LLM",
            )

        # 第 2 步：粗筛命中但没有正文 -> 补抓详情（卡片要从正文里提截止日期）
        if not notice.content:
            notice = self.source.fetch_detail(notice)

        # 第 3 步：单次结构化调用，让 LLM 产出 JSON 卡片
        card = self.llm.complete_structured(
            system=IDENTIFY_SYSTEM_PROMPT,
            user=(
                f"通知标题：{notice.title}\n"
                f"通知网址：{notice.source_url}\n"
                f"通知正文：\n{notice.content[:MAX_CONTENT_CHARS]}"
            ),
            schema=CARD_SCHEMA,
        )

        # 第 4 步：按卡片组装结果
        if not card.get("is_competition"):
            return ScanOutcome(
                notice=notice,
                is_competition=False,
                competition=None,
                reason=f"LLM 判定非比赛：{card.get('reason', '未给出理由')}",
                llm_called=True,
            )

        competition = Competition(
            # 模型万一没给名字，退回用通知标题顶着，卡片不至于开天窗
            name=card.get("name") or notice.title,
            notice_url=notice.source_url,
            type=card.get("type") or "unknown",
            deadline=parse_date(card.get("deadline")),
            evidence=card.get("evidence", ""),
        )
        return ScanOutcome(
            notice=notice,
            is_competition=True,
            competition=competition,
            reason=card.get("reason", ""),
            llm_called=True,
        )
