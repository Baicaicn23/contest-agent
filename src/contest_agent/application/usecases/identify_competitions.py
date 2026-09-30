"""identify_competitions 用例：把一批通知变成"比赛卡片 + 判断理由"（P2 核心）。

每条通知的处理流程：
    1. 关键词粗筛：没沾比赛词的直接跳过（零成本挡掉大部分杂事）；
    2. 粗筛命中但没有正文 -> 补抓详情（截止日期等信息藏在正文里）；
    3. 查持久记忆：这条通知判断过（且正文没变）就直接用记住的结论，
       不花 LLM 的钱（M2）；
    4. 记忆没有才调 LLM 做单次结构化调用，产出 JSON 卡片，
       并把结论写回记忆供下次使用；
    5. is_competition=true 就地组装 Competition 实体；false 记下理由。

架构边界（开发文档 §3）：识别/提取走单次结构化调用，不走 agent 循环——
一问一答就能完成的事，不需要让模型反复决策。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ...domain.entities import Competition, Notice, parse_date
from ...domain.ports import CompetitionRepositoryPort, LlmPort, MemoryPort, NoticeSourcePort
from ..cost import BudgetExceededError
from ..keyword_filter import keyword_hit
from ..prompts import CARD_SCHEMA, IDENTIFY_SYSTEM_PROMPT
from ..recorder import TaskRecorder

# 发给 LLM 的正文上限（字符）。再长的通知，开头 6000 字也足够判断；
# 截断同时控制了 token 成本，避免长通知把上下文窗口顶爆
MAX_CONTENT_CHARS = 6000


def _content_fingerprint(notice: Notice) -> str:
    """通知正文的"指纹"（哈希）：记忆靠它判断"这条通知的正文变没变"。

    只对发给 LLM 的那截正文取指纹（截断规则和识别时完全一致）——
    页面脚注变了但正文没变的通知，不应该让记忆失效重判。
    """
    raw = notice.content[:MAX_CONTENT_CHARS]
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ScanOutcome:
    """一条通知的识别结果：是否比赛、卡片（如是）、给人看的理由。"""

    notice: Notice
    is_competition: bool
    competition: Competition | None
    reason: str           # 人能读的判断理由（粗筛挡下 / LLM 的判断依据 / 记忆命中）
    llm_called: bool = False  # 这条有没有真的动用 LLM（被粗筛挡下或记忆命中的为 False）
    from_memory: bool = False  # M2：这条结论是直接从持久记忆翻出来的吗


class IdentifyCompetitions:
    """识别比赛：扫描 -> 粗筛 -> 补详情 -> 查记忆 -> LLM 识别 -> 写记忆 -> 卡片 -> 入库。"""

    def __init__(
        self,
        source: NoticeSourcePort,
        llm: LlmPort,
        competition_store: CompetitionRepositoryPort | None = None,
        memory: MemoryPort | None = None,
        recorder: TaskRecorder | None = None,
    ):
        # 依赖注入：爬虫、LLM、仓储都从外面递进来，本类只认识端口接口
        self.source = source
        self.llm = llm
        self.competition_store = competition_store
        # 持久记忆（M2）：判过的结论存这里，重复扫描直接命中、跳过 LLM。
        # 不注入 = 关闭记忆。评测套件就必须关——评测要考的是 LLM 本身，不是缓存
        self.memory = memory
        # 会话记录器（M2）：把这次任务的轨迹逐步写进会话存档，供 sai replay 回放
        self.recorder = recorder
        # 最近一次入库统计：{"new": 新增几张卡, "existing": 已存在几张}；
        # 没配仓储就是 None。P3 起有值
        self.last_sync: dict[str, int] | None = None
        # 本次识别"新入库"的卡片清单（M3 定时推送用）：
        # last_sync 只记数量，推送需要知道"具体是哪几场新比赛"
        self.new_cards: list[Competition] = []
        # M1 预算闸门：预算熔断时把报错存这里（而不是让异常直接飞出去）。
        # 原因：熔断前已经花钱识别出的卡片必须照常入库——
        # 钱不能白花，熔断只是"别再花了"，不是"把干了活的扔掉"。
        # CLI 检查这个字段决定要不要播报熔断、返回非零退出码
        self.budget_error: str | None = None

    def execute(self, limit: int = 5) -> list[ScanOutcome]:
        """扫描最新 limit 条通知并逐条识别；有仓储就把卡片幂等入库。

        M1 起逐条捕获 BudgetExceededError：某条通知触发熔断就停下
        （不再识别后面的通知），但前面已识别的结果照常打包返回。
        M2 起全程写会话事件，结束时按结局盖状态戳（completed /
        budget_break / failed），sai replay 靠它完整回放。
        """
        if self.recorder is not None:
            self.recorder.log("user_input", text=f"识别最新 {limit} 条通知")
        notices = self.source.list_notices(limit=limit)
        outcomes: list[ScanOutcome] = []
        try:
            for notice in notices:
                try:
                    outcome = self._identify_one(notice)
                except BudgetExceededError as error:
                    self.budget_error = str(error)
                    break
                outcomes.append(outcome)
                if self.recorder is not None:
                    self.recorder.log(
                        "result",
                        url=notice.source_url,
                        title=notice.title,
                        is_competition=outcome.is_competition,
                        from_memory=outcome.from_memory,
                        llm_called=outcome.llm_called,
                    )
            self._sync_store(outcomes)
        except Exception as error:
            # 意外错误：给会话盖"失败"戳后原样抛出（调用方的异常处理不受影响）
            if self.recorder is not None:
                self.recorder.log("error", error=str(error))
                self.recorder.finish("failed")
            raise
        if self.recorder is not None:
            self.recorder.finish("budget_break" if self.budget_error else "completed")
        return outcomes

    def _sync_store(self, outcomes: list[ScanOutcome]) -> None:
        """把识别出的比赛卡片幂等入库（P3）。统计记到 last_sync，新卡记到 new_cards。"""
        self.new_cards = []
        if self.competition_store is None:
            return
        new_count = existing_count = 0
        for outcome in outcomes:
            if not outcome.is_competition or outcome.competition is None:
                continue  # 非比赛没有卡片可存
            if self.competition_store.save_if_absent(outcome.competition):
                new_count += 1
                self.new_cards.append(outcome.competition)  # 新面孔，推送就推它们
            else:
                existing_count += 1
        self.last_sync = {"new": new_count, "existing": existing_count}

    def _recall_verdict(self, notice: Notice) -> ScanOutcome | None:
        """查记忆：这条通知判断过且正文没变，就重建结论直接返回；否则 None。

        记忆的 value 里存了正文指纹（_content_fingerprint）——指纹对不上
        说明通知内容改了，旧结论不可信，必须重判（返回 None）。
        """
        if self.memory is None:
            return None
        cached = self.memory.recall(f"verdict:{notice.source_url}")
        if not cached:
            return None
        if cached.get("content_hash") != _content_fingerprint(notice):
            return None  # 正文变了：旧结论作废，走 LLM 重判
        if not cached.get("is_competition"):
            return ScanOutcome(
                notice=notice,
                is_competition=False,
                competition=None,
                reason=f"记忆命中（曾判定非比赛）：{cached.get('reason', '')}",
                from_memory=True,
            )
        competition = Competition(
            name=cached.get("name") or notice.title,
            notice_url=notice.source_url,
            type=cached.get("type") or "unknown",
            deadline=parse_date(cached.get("deadline")),
            evidence=cached.get("evidence", ""),
        )
        return ScanOutcome(
            notice=notice,
            is_competition=True,
            competition=competition,
            reason=f"记忆命中：{cached.get('reason', '')}",
            from_memory=True,
        )

    def _remember_verdict(self, notice: Notice, card: dict) -> None:
        """把 LLM 的判断结论写进记忆（比赛与否都记——非比赛的结论同样值钱）。"""
        if self.memory is None:
            return
        self.memory.remember(
            f"verdict:{notice.source_url}",
            {
                "content_hash": _content_fingerprint(notice),
                "is_competition": bool(card.get("is_competition")),
                "name": card.get("name"),
                "type": card.get("type"),
                "deadline": card.get("deadline"),
                "evidence": card.get("evidence", ""),
                "reason": card.get("reason", ""),
            },
        )

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

        # 第 3 步：查持久记忆——判断过且正文没变就直接用，一个子儿不花
        remembered = self._recall_verdict(notice)
        if remembered is not None:
            return remembered

        # 第 4 步：记忆没有 -> 单次结构化调用，让 LLM 产出 JSON 卡片
        card = self.llm.complete_structured(
            system=IDENTIFY_SYSTEM_PROMPT,
            user=(
                f"通知标题：{notice.title}\n"
                f"通知网址：{notice.source_url}\n"
                f"通知正文：\n{notice.content[:MAX_CONTENT_CHARS]}"
            ),
            schema=CARD_SCHEMA,
        )
        # 先把结论写进记忆（比赛与否都记），再组装业务结果
        self._remember_verdict(notice, card)

        # 第 5 步：按卡片组装结果
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
