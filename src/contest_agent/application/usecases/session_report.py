"""session_report 用例：查询会话存档（M2）。sai sessions / sai replay / GET /sessions 的后端。

查询本身很薄（转手仓储），单独立用例是为了守住分层纪律：
CLI 和 HTTP 都只调用例，不直接摸仓储——哪天换存档后端，这两层一行不改。
"""

from __future__ import annotations

from ...domain.entities import SessionEvent, SessionSummary
from ...domain.ports import SessionArchivePort


class SessionReport:
    """会话存档的查询口。"""

    def __init__(self, archive: SessionArchivePort):
        self.archive = archive

    def list_recent(self, limit: int = 20) -> list[SessionSummary]:
        """最近 limit 个会话概要（新的在前）。"""
        return self.archive.list_sessions(limit=limit)

    def detail(self, session_id: int) -> tuple[SessionSummary, list[SessionEvent]]:
        """一个会话的完整轨迹；不存在抛 KeyError（调用方翻译成人话）。"""
        return self.archive.get_session(session_id)
