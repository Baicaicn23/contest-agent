"""领域实体：纯数据，不依赖任何外层（洋葱的最内层）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Notice:
    """一条官网通知（P1 爬虫产出）。字段随 P1 落地补全。"""

    source_url: str
    title: str
    published_at: datetime | None = None
    content: str = ""
    attachments: list[str] = field(default_factory=list)


@dataclass
class Competition:
    """一条比赛卡片（P2 识别提取产出）。字段随 P2 落地补全。"""

    name: str
    notice_url: str
    type: str = "unknown"  # deliverable（交付物型）/ exam（考试型）/ unknown
    deadline: datetime | None = None
    evidence: str = ""     # 原文证据片段，防幻觉
