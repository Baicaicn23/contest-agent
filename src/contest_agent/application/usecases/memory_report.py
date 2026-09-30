"""memory_report 用例：查看/清理持久记忆（M2）。sai memory 的后端。

系统"记了什么"必须对人可见、可清——记忆不可见就成了黑魔法，
出错（记错了结论）时用户要有办法发现和清除。
"""

from __future__ import annotations

from ...domain.entities import MemoryEntry
from ...domain.ports import MemoryPort


class MemoryReport:
    """持久记忆的查询与清理口。"""

    def __init__(self, memory: MemoryPort):
        self.memory = memory

    def entries(self, limit: int = 50) -> list[MemoryEntry]:
        """最近的记忆条目（新的在前）。"""
        return self.memory.list_entries(limit=limit)

    def count(self) -> int:
        """记忆总条数。"""
        return self.memory.count()

    def clear(self) -> int:
        """清空全部记忆，返回清掉了几条。

        什么时候该清？——粗筛词表大改、识别提示词换血之后，
        旧结论可能系统性过时；清空让系统重新学习一遍（花一次钱，换结论可信）。
        """
        return self.memory.forget_all()
