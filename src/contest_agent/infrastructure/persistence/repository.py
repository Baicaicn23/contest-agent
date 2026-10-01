"""仓储实现：把 domain 端口翻译成 SQLAlchemy 操作（P3）。

依赖倒置第三次实战：application 层只认识 CompetitionRepositoryPort /
NoticeRepositoryPort 接口，这两个具体类名只出现在 composition.py。

验收标准里"换内存库 URL 测试仍通过"考的就是这个设计——
测试把 DATABASE_URL 换成 sqlite:///:memory:（或临时文件），
仓储和业务代码一行不改，测试照样全绿。这就是可迁移性的兑现。
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ...domain.entities import (
    Competition,
    MemoryEntry,
    Notice,
    ProjectInfo,
    SessionEvent,
    SessionSummary,
    UsageEntry,
)
from .models import (
    Base,
    CompetitionModel,
    MemoryModel,
    NoticeModel,
    ProjectModel,
    SessionEventModel,
    SessionModel,
    UsageRecordModel,
)


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
        # 内存库才能像文件库一样连续使用。
        # 复用单连接意味着跨线程也要允许（TestClient 的流式响应、
        # FastAPI 的线程池都在别的线程碰它），所以同样关掉线程检查
        engine_kwargs["poolclass"] = StaticPool
        connect_args["check_same_thread"] = False

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


class SqliteUsageRepository:
    """usage_records 表的仓储，实现 UsageRepositoryPort（M1 成本台账）。

    只有两个动作：记一笔（record）、按条件查流水（list_entries）。
    聚合汇总（求和、分组）不在这层做——那是 CostReport 用例的业务逻辑，
    放在用例层才能用假仓储离线测试。
    """

    def __init__(self, database_url: str):
        self._engine = _build_engine(database_url)
        Base.metadata.create_all(self._engine)
        self._migrate_add_session_id()
        self._session_factory = sessionmaker(bind=self._engine)

    def _migrate_add_session_id(self) -> None:
        """给 M1 时代建的老库就地补 session_id 列（M2）。

        为什么做这个小迁移而不是按 v1 约定"删库重建"？——usage_records 里
        存的是真实花掉的钱的记录，删了就没了（通知和卡片可以重爬，
        账本不行）。create_all 只会建缺的表、不会改已有的表，
        所以用 PRAGMA 查列、缺就 ALTER——幂等，跑多少遍都安全。
        等这类小迁移多到难受的那天，再正经开 Alembic（开发文档 §6 预警）。
        """
        with self._engine.connect() as conn:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(usage_records)")}
            if "session_id" not in columns:
                conn.exec_driver_sql("ALTER TABLE usage_records ADD COLUMN session_id INTEGER")
                conn.commit()

    def record(self, entry: UsageEntry) -> None:
        """记一笔 LLM 调用流水。created_at 没写就补当前时间。"""
        with self._session_factory() as session, session.begin():
            session.add(
                UsageRecordModel(
                    task_type=entry.task_type,
                    profile_name=entry.profile_name,
                    model=entry.model,
                    prompt_tokens=entry.prompt_tokens,
                    completion_tokens=entry.completion_tokens,
                    cost_yuan=entry.cost_yuan,
                    note=entry.note,
                    created_at=entry.created_at or datetime.now(),
                    session_id=entry.session_id,
                )
            )

    def list_entries(
        self, task_type: str | None = None, on_date: date | None = None,
        session_id: int | None = None, since: datetime | None = None,
    ) -> list[UsageEntry]:
        """按条件查流水，按时间正序返回（对账习惯：从早到晚）。

        过滤思路：task_type 精确匹配；on_date 用"当天零点 <= 时刻 < 次日零点"
        的区间判断——数据库里存的是带时间的 datetime，按天查就是圈定这个区间。
        """
        query = select(UsageRecordModel).order_by(UsageRecordModel.created_at)
        if task_type is not None:
            query = query.where(UsageRecordModel.task_type == task_type)
        if on_date is not None:
            day_start = datetime(on_date.year, on_date.month, on_date.day)
            day_end = datetime(on_date.year, on_date.month, on_date.day) + timedelta(days=1)
            query = query.where(UsageRecordModel.created_at >= day_start,
                                UsageRecordModel.created_at < day_end)
        if session_id is not None:
            query = query.where(UsageRecordModel.session_id == session_id)
        if since is not None:
            query = query.where(UsageRecordModel.created_at >= since)
        with self._session_factory() as session:
            rows = session.scalars(query).all()
            return [
                UsageEntry(
                    task_type=row.task_type,
                    profile_name=row.profile_name,
                    model=row.model,
                    prompt_tokens=row.prompt_tokens,
                    completion_tokens=row.completion_tokens,
                    cost_yuan=row.cost_yuan,
                    note=row.note,
                    created_at=row.created_at,
                    session_id=row.session_id,
                )
                for row in rows
            ]


class SqliteMemoryRepository:
    """memories 表的仓储，实现 MemoryPort（M2 持久记忆）。"""

    def __init__(self, database_url: str):
        self._engine = _build_engine(database_url)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)

    def remember(self, key: str, value: dict) -> None:
        """记住一条结论：不存在就插入，已存在就覆盖（并刷新 updated_at）。"""
        with self._session_factory() as session, session.begin():
            row = session.scalar(select(MemoryModel).where(MemoryModel.key == key))
            if row is None:
                session.add(MemoryModel(key=key, value=value, updated_at=datetime.now()))
            else:
                row.value = value
                row.updated_at = datetime.now()

    def recall(self, key: str) -> dict | None:
        """按 key 取记忆；没记过返回 None。"""
        with self._session_factory() as session:
            row = session.scalar(select(MemoryModel).where(MemoryModel.key == key))
            return row.value if row is not None else None

    def forget_all(self) -> int:
        """清空全部记忆，返回清掉了几条（给 CLI 播报）。"""
        with self._session_factory() as session, session.begin():
            rows = session.scalars(select(MemoryModel)).all()
            count = len(rows)
            for row in rows:
                session.delete(row)
        return count

    def list_entries(self, limit: int = 50) -> list[MemoryEntry]:
        """按更新时间倒序列出最近的记忆。"""
        with self._session_factory() as session:
            rows = session.scalars(
                select(MemoryModel).order_by(MemoryModel.updated_at.desc()).limit(limit)
            ).all()
            return [
                MemoryEntry(key=row.key, value=row.value or {},
                            created_at=row.created_at, updated_at=row.updated_at)
                for row in rows
            ]

    def count(self) -> int:
        """记忆总条数。"""
        with self._session_factory() as session:
            return len(session.scalars(select(MemoryModel.id)).all())


class SqliteProjectRepository:
    """projects 表的仓储，实现 ProjectStorePort（M5 手动项目）。"""

    def __init__(self, database_url: str):
        self._engine = _build_engine(database_url)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)

    def create(self, name: str) -> int:
        with self._session_factory() as session, session.begin():
            row = ProjectModel(name=name)
            session.add(row)
            session.flush()
            return row.id

    def delete(self, project_key: str) -> bool:
        """删除手动项目（M8）。键形如 manual:3；行不存在或非手动键返回 False。"""
        if not project_key.startswith("manual:"):
            return False
        pid = int(project_key.split(":", 1)[1])
        with self._session_factory() as session, session.begin():
            row = session.get(ProjectModel, pid)
            if row is None:
                return False
            session.delete(row)
            return True

    def list_manual(self) -> list[ProjectInfo]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(ProjectModel).order_by(ProjectModel.id.desc())
            ).all()
            return [
                ProjectInfo(key=f"manual:{row.id}", name=row.name, source="manual")
                for row in rows
            ]


class SqliteSessionRepository:
    """agent_sessions + session_events 两表的仓储，实现 SessionArchivePort（M2）。

    M5 起 sessions 支持 project_key（归属工作区项目）与按项目计数。
    """

    def __init__(self, database_url: str):
        self._engine = _build_engine(database_url)
        Base.metadata.create_all(self._engine)
        self._migrate_add_project_key()
        self._session_factory = sessionmaker(bind=self._engine)

    def _migrate_add_project_key(self) -> None:
        """给 M2 时代建的老库就地补 project_key 列（幂等，沿 usage_records 的先例）。"""
        with self._engine.connect() as conn:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(agent_sessions)")}
            if "project_key" not in columns:
                conn.exec_driver_sql(
                    "ALTER TABLE agent_sessions ADD COLUMN project_key VARCHAR(128)"
                )
                conn.commit()

    def create_session(self, task_type: str, note: str = "") -> int:
        """开新会话，返回自增编号。"""
        with self._session_factory() as session, session.begin():
            row = SessionModel(task_type=task_type, note=note)
            session.add(row)
            session.flush()  # flush 后自增主键才回填到对象上
            return row.id

    def append_event(self, session_id: int, kind: str, payload: dict) -> None:
        """追加事件：序号 = 该会话当前最大序号 + 1（仓储负责发号，调用方不用管）。"""
        with self._session_factory() as session, session.begin():
            max_seq = session.scalar(
                select(SessionEventModel.seq)
                .where(SessionEventModel.session_id == session_id)
                .order_by(SessionEventModel.seq.desc())
                .limit(1)
            )
            session.add(
                SessionEventModel(session_id=session_id, kind=kind,
                                  payload=payload, seq=(max_seq or 0) + 1)
            )

    def finish_session(self, session_id: int, status: str) -> None:
        """标记会话结束并盖结束时间戳。"""
        with self._session_factory() as session, session.begin():
            row = session.get(SessionModel, session_id)
            if row is not None:
                row.status = status
                row.ended_at = datetime.now()

    def _to_summary(self, row: SessionModel, event_count: int,
                    cost: float | None, llm_calls: int = 0,
                    prompt_tokens: int | None = None) -> SessionSummary:
        """ORM 行 -> 领域概要对象（转换规则集中一处）。

        cost 为 None 且 llm_calls 为 0 = 这次任务根本没调过 LLM（纯粗筛/纯记忆），
        显示上就是"¥0"；cost 为 None 但有调用 = 有调用没配上单价，才是"费用未知"。
        """
        return SessionSummary(
            id=row.id, task_type=row.task_type, note=row.note or "",
            status=row.status, started_at=row.started_at, ended_at=row.ended_at,
            event_count=event_count, cost_yuan=cost, llm_calls=llm_calls,
            project_key=row.project_key, prompt_tokens=prompt_tokens,
        )

    def bind_session(self, session_id: int, project_key: str) -> bool:
        """把会话归属到某个工作区项目。找不到会话返回 False。"""
        with self._session_factory() as session, session.begin():
            row = session.get(SessionModel, session_id)
            if row is None:
                return False
            row.project_key = project_key
        return True

    def set_status(self, session_id: int, status: str) -> bool:
        """直设会话状态（M8）：聊天是"可续聊的持久会话"，一轮回复完成
        置 completed、下一轮开始置回 running——"运行中"从此表示
        "正在生成回复"，而不是"这个会话还没关"。"""
        with self._session_factory() as session, session.begin():
            row = session.get(SessionModel, session_id)
            if row is None:
                return False
            row.status = status
        return True

    def unbind_project(self, project_key: str) -> int:
        """解绑某项目下的全部会话（M8 删除项目用）：project_key 置空，会话本体保留。

        返回解绑的会话数——"删了项目，几个会话回到了未归类"是可上报的事实。
        """
        with self._session_factory() as session, session.begin():
            rows = session.scalars(
                select(SessionModel).where(SessionModel.project_key == project_key)
            ).all()
            for row in rows:
                row.project_key = None
            return len(rows)

    def list_sessions(self, limit: int = 20) -> list[SessionSummary]:
        """最近 limit 个会话概要（新任务在前），附事件数与台账花费。

        事件数与花费是两笔子查询：事件数按 session_id 分组计数；
        花费从 usage_records 按 session_id 汇总——账目只认成本台账一份，
        会话表不重复存钱，避免两处数字对不上。
        """
        with self._session_factory() as session:
            rows = session.scalars(
                select(SessionModel).order_by(SessionModel.id.desc()).limit(limit)
            ).all()
            event_counts: dict[int, int] = dict(session.execute(
                select(SessionEventModel.session_id, func.count(SessionEventModel.id))
                .group_by(SessionEventModel.session_id)
            ).all())
            costs: dict[int, float] = {}
            call_counts: dict[int, int] = {}
            for sid, total in session.execute(
                select(UsageRecordModel.session_id, func.sum(UsageRecordModel.cost_yuan))
                .where(UsageRecordModel.session_id.isnot(None))
                .group_by(UsageRecordModel.session_id)
            ).all():
                if sid is not None and total is not None:
                    costs[sid] = float(total)
            for sid, calls in session.execute(
                select(UsageRecordModel.session_id, func.count(UsageRecordModel.id))
                .where(UsageRecordModel.session_id.isnot(None))
                .group_by(UsageRecordModel.session_id)
            ).all():
                if sid is not None:
                    call_counts[sid] = int(calls)
            # 累计输入 token（M9）：composer 的"上下文 %"数据源——
            # 每轮 prompt_tokens 都含完整历史，最后一轮的值即当前上下文占用；
            # 取 SUM 会重复计数，所以取 MAX（最接近"现在"的那一轮）
            prompt_by_session: dict[int, int] = {}
            for sid, total in session.execute(
                select(UsageRecordModel.session_id, func.max(UsageRecordModel.prompt_tokens))
                .where(UsageRecordModel.session_id.isnot(None))
                .group_by(UsageRecordModel.session_id)
            ).all():
                if sid is not None and total is not None:
                    prompt_by_session[sid] = int(total)
            return [
                self._to_summary(row, event_counts.get(row.id, 0), costs.get(row.id),
                                 call_counts.get(row.id, 0),
                                 prompt_by_session.get(row.id))
                for row in rows
            ]

    def get_session(self, session_id: int) -> tuple[SessionSummary, list[SessionEvent]]:
        """取会话完整明细；找不到抛 KeyError（调用方翻译成 404/人话）。"""
        with self._session_factory() as session:
            row = session.get(SessionModel, session_id)
            if row is None:
                raise KeyError(f"会话 {session_id} 不存在")
            event_rows = session.scalars(
                select(SessionEventModel)
                .where(SessionEventModel.session_id == session_id)
                .order_by(SessionEventModel.seq)
            ).all()
            count_row = session.execute(
                select(func.count(SessionEventModel.id))
                .where(SessionEventModel.session_id == session_id)
            ).scalar()
            cost_row = session.execute(
                select(func.sum(UsageRecordModel.cost_yuan))
                .where(UsageRecordModel.session_id == session_id)
            ).scalar()
            calls_row = session.execute(
                select(func.count(UsageRecordModel.id))
                .where(UsageRecordModel.session_id == session_id)
            ).scalar()
            summary = self._to_summary(
                row, count_row or 0,
                float(cost_row) if cost_row is not None else None,
                calls_row or 0,
            )
            events = [
                SessionEvent(seq=e.seq, kind=e.kind, payload=e.payload or {},
                             created_at=e.created_at)
                for e in event_rows
            ]
            return summary, events
