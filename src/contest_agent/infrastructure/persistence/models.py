"""SQLAlchemy ORM 模型：notices / competitions 两表（P3）。

ORM（对象关系映射）：用 Python 类描述表结构，读写数据库就是操作对象，
不用手拼 SQL。类比 Java 的 JPA/Hibernate：一个类对应一张表，
一个字段对应一列，Base 相当于被 @Entity 扫描的根。

v1 故意不上迁移工具（Alembic）：表结构变了就删掉 data/*.db 重建——
数据是爬来的，随时可再生，用开发速度换仪式感是划算的；
真到需要保历史数据的那天再引 Alembic（开发文档 §6 有预警）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有表模型的公共基类：SQLAlchemy 靠它收集"一共有哪些表"。"""


class NoticeModel(Base):
    """notices 表：爬到的通知（扫描台账）。source_url 唯一，天然幂等。"""

    __tablename__ = "notices"

    id: Mapped[int] = mapped_column(primary_key=True)  # 自增主键，数据库自己发号
    source_url: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    # unique=True 让数据库层面也挡重复：就算代码判重出了 bug，数据库兜底
    title: Mapped[str] = mapped_column(String(512))
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    # JSON 列：SQLite 支持把列表存成 JSON 文本，取出来自动变回列表
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class CompetitionModel(Base):
    """competitions 表：识别出的比赛卡片（核心资产）。url_hash 唯一做幂等。"""

    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 幂等键：来源 URL + 比赛名 的哈希（计算规则见 repository.py）
    url_hash: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    type: Mapped[str] = mapped_column(String(16), default="unknown")
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    evidence: Mapped[str] = mapped_column(Text, default="")
    notice_url: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class UsageRecordModel(Base):
    """usage_records 表：LLM 调用流水账（M1 成本台账）。

    定位和 notices 表（扫描台账）一样是"只增不改"的流水：
    每次调用 LLM 记一行，账本永不涂改，错了就错着（对账靠人）。
    成本台账是 v2 其他一切优化的度量衡——压缩省没省钱、路由选没选对，
    都拿这张表说话。
    """

    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    # index=True：最常用的查询是"按任务聚合"（如 identify 花了多少），建索引免全表扫
    profile_name: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    # nullable=True：档案没配单价时记 None——记不了钱，但 token 量照记
    cost_yuan: Mapped[float | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    # 按天查账也是高频操作（"今天花了多少"），同样建索引
