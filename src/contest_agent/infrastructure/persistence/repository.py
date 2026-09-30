"""仓储实现：把 domain 端口翻译成 SQLAlchemy 操作（P3）。

依赖倒置第三次实战：application 层只认识 CompetitionRepositoryPort /
NoticeRepositoryPort 接口，这两个具体类名只出现在 composition.py。

验收标准里"换内存库 URL 测试仍通过"考的就是这个设计——
测试把 DATABASE_URL 换成 sqlite:///:memory:（或临时文件），
仓储和业务代码一行不改，测试照样全绿。这就是可迁移性的兑现。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ...domain.entities import Competition, Notice
from .models import Base, CompetitionModel, NoticeModel


def _build_engine(database_url: str) -> Engine:
    """按连接串创建数据库引擎，处理 SQLite 的三个特殊点。

    连接串格式（类比 JDBC 的 jdbc:mysql://...）：
        sqlite:///data/contest_agent.db   文件库
        sqlite:///:memory:                内存库（测试用，关进程即消失）
    """
    connect_args: dict = {}
    engine_kwargs: dict = {}

    if database_url.startswith("sqlite") and not database_url.endswith(":memory:"):
        # 坑一（全新克隆必踩）：sqlite 不会自动创建文件所在的目录，
        # git 又不跟踪空目录——所以克隆下来 data/ 不存在，直接启动会报
        # "unable to open database file"。这里自动把目录建出来。
        db_file = database_url.split("sqlite:///", 1)[-1]
        if db_file:
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)
        # 坑二：SQLite 默认禁止跨线程共用同一个连接，
        # FastAPI 的多线程环境和测试工具都需要这个开关
        connect_args["check_same_thread"] = False

    if database_url.endswith(":memory:"):
        # 坑三：内存库的默认行为是"每个新连接 = 全新的空库"，
        # 第二个会话会"找不到表"。StaticPool 让所有会话复用同一个连接，
        # 内存库才能像文件库一样连续使用
        engine_kwargs["poolclass"] = StaticPool

    return create_engine(database_url, connect_args=connect_args, **engine_kwargs)


def competition_hash(competition: Competition) -> str:
    """比赛卡片的幂等键：来源 URL + 比赛名 的 SHA256 前 16 位。

    为什么哈希而不是"两列联合唯一索引"？——把判重规则钉死在一个函数里：
    以后想调整规则（比如忽略名字里的空格），只改这一处。
    开发文档 §6 的约定：幂等键 = 来源 URL + 标题哈希。
    """
    raw = f"{competition.notice_url}|{competition.name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class SqliteNoticeRepository:
    """notices 表的仓储，实现 NoticeRepositoryPort。"""

    def __init__(self, database_url: str):
        self._engine = _build_engine(database_url)
        Base.metadata.create_all(self._engine)  # 表不存在就建，存在就跳过
        self._session_factory = sessionmaker(bind=self._engine)

    def save_notice_if_absent(self, notice: Notice) -> bool:
        """幂等写入：以 source_url 判重。返回是否新写入。"""
        with self._session_factory() as session, session.begin():
            # session.begin() 的事务在 with 块正常结束时自动提交，异常自动回滚
            exists = session.scalar(
                select(NoticeModel).where(NoticeModel.source_url == notice.source_url)
            )
            if exists is not None:
                return False
            session.add(
                NoticeModel(
                    source_url=notice.source_url,
                    title=notice.title,
                    published_at=notice.published_at,
                    content=notice.content,
                    attachments=notice.attachments,
                )
            )
        return True

    def list_notices(self) -> list[Notice]:
        """按发布时间倒序列出全部通知（领域对象，不是 ORM 对象）。"""
        with self._session_factory() as session:
            rows = session.scalars(
                select(NoticeModel).order_by(NoticeModel.published_at.desc())
            ).all()
            return [
                Notice(
                    source_url=row.source_url,
                    title=row.title,
                    published_at=row.published_at,
                    content=row.content,
                    attachments=row.attachments or [],
                )
                for row in rows
            ]


class SqliteCompetitionRepository:
    """competitions 表的仓储，实现 CompetitionRepositoryPort。"""

    def __init__(self, database_url: str):
        self._engine = _build_engine(database_url)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)

    def save_if_absent(self, competition: Competition) -> bool:
        """幂等写入：以 url_hash（来源URL+比赛名）判重。返回是否新写入。"""
        url_hash = competition_hash(competition)
        with self._session_factory() as session, session.begin():
            exists = session.scalar(
                select(CompetitionModel).where(CompetitionModel.url_hash == url_hash)
            )
            if exists is not None:
                return False
            session.add(
                CompetitionModel(
                    url_hash=url_hash,
                    name=competition.name,
                    type=competition.type,
                    deadline=competition.deadline,
                    evidence=competition.evidence,
                    notice_url=competition.notice_url,
                )
            )
        return True

    def list_all(self) -> list[Competition]:
        """列出全部比赛卡片，按截止日期升序（没写截止的排最后）。"""
        with self._session_factory() as session:
            rows = session.scalars(select(CompetitionModel)).all()
        competitions = [
            Competition(
                name=row.name,
                notice_url=row.notice_url,
                type=row.type,
                deadline=row.deadline,
                evidence=row.evidence,
            )
            for row in rows
        ]
        # 排序技巧：(没有截止日期?, 截止日期)。
        # False < True，所以有日期的都排前面并按时间升序；
        # 没日期的一组里第二个元素全是 None（相等，不用比较），稳定排在最后
        return sorted(competitions, key=lambda c: (c.deadline is None, c.deadline))

    def count(self) -> int:
        """卡片总数（给报告和 CLI 展示用）。"""
        with self._session_factory() as session:
            return len(session.scalars(select(CompetitionModel.id)).all())
