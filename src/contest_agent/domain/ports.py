"""领域端口：四份"能力招聘启事"，外层基础设施照着它来实现。

为什么需要端口（ports）？——domain 层说"我需要有人会爬通知、会存比赛、
会调大模型、会搜索"，但它不应该关心具体是谁在干（requests？别家爬虫库？
DeepSeek？GLM？）。端口就是把"需要什么能力"写成接口。

写法用的是 Python 的 Protocol（协议类），可以理解成 Java 的 interface：
只声明"有哪些方法"，不写实现。谁实现了这些方法，谁就"符合这个协议"，
这就是依赖倒置——业务依赖接口，不依赖具体实现。

实际收益（以后会反复体会到）：
- 换数据库 = 换一个仓储实现类，业务代码一行不动；
- 写测试 = 传一个假的实现（比如内存字典假装数据库），又快又稳。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from .entities import Competition, Notice, UsageEntry


class NoticeSourcePort(Protocol):
    """能力一：能从指定网站拿到通知（P1 由 infrastructure/crawler 实现）。"""

    def list_notices(self, limit: int = 10) -> list[Notice]:
        """拉取最新的通知列表（只要标题和网址这些基本信息）。"""
        ...

    def fetch_detail(self, notice: Notice) -> Notice:
        """去一条通知的详情页，把正文、附件补充完整后返回同一个对象。"""
        ...


class CompetitionRepositoryPort(Protocol):
    """能力二：能把识别出的比赛存起来、查出来（P3 由 infrastructure/persistence 实现）。"""

    def save_if_absent(self, competition: Competition) -> bool:
        """幂等写入：还没存过才存，存过就跳过。

        "幂等"= 同一件事做多少遍，结果都一样。
        判断标准是（来源网址 + 标题）——重复扫描时同一条比赛不该存两遍。
        返回 True 表示这次是新写入的。
        """
        ...

    def list_all(self) -> list[Competition]:
        """列出所有已识别的比赛。"""
        ...


class NoticeRepositoryPort(Protocol):
    """能力五：能存取爬到的通知（P3 由 infrastructure/persistence 实现）。

    通知入库的定位是"扫描台账"：哪些通知见过、什么时候见的。
    有了它，重复扫描才做得到"0 重复入库"。
    """

    def save_notice_if_absent(self, notice: Notice) -> bool:
        """幂等写入：以来源 URL 判重。返回 True 表示这次是新写入的。"""
        ...

    def list_notices(self) -> list[Notice]:
        """列出全部已见过的通知。"""
        ...


class LlmPort(Protocol):
    """能力三：会调用大模型（P2 由 infrastructure/llm 实现，走 OpenAI 兼容接口）。

    注意：P4 起材料生成的 agent 循环由 AgentScope 框架驱动（ADR-002），
    走的是 harness/agent_factory 的组装，不经过本端口；
    本端口只服务"单次结构化调用"这一类任务。
    """

    def complete_structured(self, system: str, user: str, schema: dict) -> dict:
        """单次结构化调用：给提示词和期望的 JSON 格式，返回符合格式的字典。

        识别/提取这类"一问一答"的任务走这里，不走 agent 循环——
        更快、更便宜、更好测。
        """
        ...


class UsageRepositoryPort(Protocol):
    """能力六：能把每次 LLM 调用的花费记下来、按条件查出来（M1 由 infrastructure/persistence 实现）。

    成本台账是 v2 一切优化的"度量衡"：没有它，压缩省没省钱、
    路由选没选对模型，全都只能靠感觉。
    """

    def record(self, entry: UsageEntry) -> None:
        """记一笔流水（一次 LLM 调用）。只增不改不删——账本不能涂改。"""
        ...

    def list_entries(
        self, task_type: str | None = None, on_date: date | None = None,
        session_id: int | None = None, since: datetime | None = None,
    ) -> list[UsageEntry]:
        """按条件查流水：不传条件 = 全部；可按任务、按天、按会话、按起始时间过滤。"""
        ...


class MemoryPort(Protocol):
    """能力七：能记住"学过的结论"、下次直接翻出来用（M2 由 infrastructure/persistence 实现）。

    典型场景：某条通知已经判断过"不是比赛"，记住这个结论，
    重复扫描再遇到它就直接跳过 LLM——省钱省时不降级。
    """

    def remember(self, key: str, value: dict) -> None:
        """记住一条结论。同一个 key 再记 = 覆盖更新（结论可以随时间修正）。"""
        ...

    def recall(self, key: str) -> dict | None:
        """按 key 取记忆；没记过返回 None。"""
        ...

    def forget_all(self) -> int:
        """清空全部记忆（sai memory clear 用），返回清掉了几条。"""
        ...

    def list_entries(self, limit: int = 50) -> list[MemoryEntry]:
        """列出最近的记忆（sai memory 查看，让人知道系统"记了什么"）。"""
        ...

    def count(self) -> int:
        """记忆总条数。"""
        ...


class SessionArchivePort(Protocol):
    """能力八：能把一次任务的完整轨迹存下来、按需回放（M2 由 infrastructure/persistence 实现）。

    借鉴 pi 的"会话后端独立、接口可换"思想：业务层只认这个接口，
    存 SQLite 还是别的（甚至内存），随时可换。
    """

    def create_session(self, task_type: str, note: str = "") -> int:
        """开一个新会话（任务开始时调用），返回会话编号。"""
        ...

    def append_event(self, session_id: int, kind: str, payload: dict) -> None:
        """往会话里追加一条事件（序号由仓储自动递增）。"""
        ...

    def finish_session(self, session_id: int, status: str) -> None:
        """标记会话结束：completed / failed / budget_break。"""
        ...

    def list_sessions(self, limit: int = 20) -> list[SessionSummary]:
        """列出最近的会话概要（带事件数与该会话的台账花费）。"""
        ...

    def get_session(self, session_id: int) -> tuple[SessionSummary, list[SessionEvent]]:
        """取一个会话的完整明细：概要 + 按序号排好的全部事件。找不到抛 KeyError。"""
        ...


class PushPort(Protocol):
    """能力九：能把一条通知推送到外部（M3 由 infrastructure/push 实现）。

    "自动盯官网"的最后一步：发现了新比赛，得有人告诉你——
    webhook / 邮件 / 本地文件，谁配置了就用谁，业务不关心通道细节。
    """

    def send(self, title: str, content: str) -> None:
        """推送一条通知。失败抛异常（由调用方决定降级策略——
        一个通道挂了不能影响其他通道）。"""
        ...

    @property
    def channel_name(self) -> str:
        """通道名（webhook / smtp / file），推送结果播报用。"""
        ...


class SearchPort(Protocol):
    """能力四：会联网搜索、读网页、验证链接，而且失败了不炸（P5 由 infrastructure/search 实现）。

    "带降级"贯穿三个方法：网络上谁都说不准，
    失败时返回空结果/False/错误说明，主流程必须能带着"没搜到"继续走。
    """

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """搜索并返回前 top_k 条结果：[{title, url, snippet}, ...]；失败返回空列表。"""
        ...

    def read_page(self, url: str, max_chars: int = 3000) -> str:
        """读取网页正文文本（截断到 max_chars）；失败返回说明文字而非抛异常。"""
        ...

    def check_url(self, url: str) -> tuple[bool, str]:
        """验证链接是否真实存在（引用存在性校验的底层）。

        返回 (是否存在, 说明)。判定尺度：
        正常响应 = 存在；404/超时/解析失败 = 不存在；
        403/429（存在但拒绝机器人）= 存在但注明。
        """
        ...
