"""领域端口：外层基础设施必须实现的接口。

依赖倒置的关键——用例只依赖这里的 Protocol，不依赖任何具体实现；
换爬虫库/换数据库/换模型供应商时，业务代码一行不动。
P0 只立接口骨架，方法签名随 P1-P5 落地补全。
"""

from __future__ import annotations

from typing import Protocol

from .entities import Competition, Notice


class NoticeSourcePort(Protocol):
    """站点通知源（P1 由 infrastructure/crawler 实现）。"""

    def list_notices(self, limit: int = 10) -> list[Notice]:
        """拉取最新通知列表。"""
        ...

    def fetch_detail(self, notice: Notice) -> Notice:
        """补全单条通知的正文与附件。"""
        ...


class CompetitionRepositoryPort(Protocol):
    """比赛仓储（P3 由 infrastructure/persistence 实现）。"""

    def save_if_absent(self, competition: Competition) -> bool:
        """幂等写入：已存在（来源 URL + 标题哈希）则跳过，返回是否新写入。"""
        ...

    def list_all(self) -> list[Competition]:
        """列出全部已识别比赛。"""
        ...


class LlmPort(Protocol):
    """LLM 调用（P2 由 infrastructure/llm 实现，openai 兼容层）。"""

    def complete_structured(self, system: str, user: str, schema: dict) -> dict:
        """单次结构化调用：识别/提取走这里，不走 agent loop。"""
        ...


class SearchPort(Protocol):
    """外部搜索 + 正文抓取，带降级（P5 由 infrastructure/search 实现）。"""

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """返回 [{title, url, snippet}]；失败时降级为空列表而非抛异常。"""
        ...
