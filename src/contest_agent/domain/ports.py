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

from typing import Protocol

from .entities import Competition, Notice


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
    """能力三：会调用大模型（P2 由 infrastructure/llm 实现，走 OpenAI 兼容接口）。"""

    def complete_structured(self, system: str, user: str, schema: dict) -> dict:
        """单次结构化调用：给提示词和期望的 JSON 格式，返回符合格式的字典。

        注意：识别/提取这类"一问一答"的任务走这里就够了，
        不需要动用 agent 循环——更快、更便宜、更好测。
        """
        ...


class SearchPort(Protocol):
    """能力四：会联网搜索并抓正文，而且失败了不炸（P5 由 infrastructure/search 实现）。"""

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """搜索并返回前 top_k 条结果：[{title, url, snippet}, ...]。

        "带降级"的意思：搜索挂了就返回空列表，而不是抛异常把整个任务搞死——
        网络上的事谁都说不准，主流程必须能带着"没搜到"继续走。
        """
        ...
