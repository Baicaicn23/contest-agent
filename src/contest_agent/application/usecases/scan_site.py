"""scan_site 用例：扫一次官网，产出通知列表（可选补抓若干条详情）。

"用例（use case）"= 一条完整的业务动作，是 application 层的主角。
它只认识 domain/ports.py 里的接口，完全不关心具体实现——
所以单元测试时可以塞"内存假爬虫"，又快又稳。

P3 起：构造时可以递进来一个 NoticeRepositoryPort（通知台账仓储），
扫到的通知会顺手幂等入库；不递就是纯扫描（P1 行为，测试兼容）。
"""

from __future__ import annotations

from ...domain.entities import Notice
from ...domain.ports import NoticeRepositoryPort, NoticeSourcePort


class ScanSite:
    """扫描一个站点源，返回通知列表；有仓储就同步台账。"""

    def __init__(
        self,
        source: NoticeSourcePort,
        notice_store: NoticeRepositoryPort | None = None,
    ):
        # 依赖注入：爬虫和仓储都从外面递进来，本类不自己创建（装配根的纪律）
        self.source = source
        self.notice_store = notice_store
        # 最近一次入库统计：{"new": 新增几条, "existing": 已存在几条}。
        # 没配仓储就是 None。用属性而不是改返回值，是为了不破坏 P1 的调用方
        self.last_sync: dict[str, int] | None = None

    def execute(
        self, limit: int = 10, detail_indexes: list[int] | None = None
    ) -> list[Notice]:
        """执行扫描。

        limit：最多返回多少条通知；
        detail_indexes：需要补抓正文的序号列表（从 1 开始数），
        比如 [1] 表示给第 1 条补抓详情。序号越界会被安全跳过。
        """
        notices = self.source.list_notices(limit=limit)
        self._sync_store(notices)

        # 只对用户点名的条目抓详情——每一条都是一次真实 HTTP 请求，
        # 不点名就不抓，省流量也省时间
        for index in detail_indexes or []:
            if 1 <= index <= len(notices):
                notices[index - 1] = self.source.fetch_detail(notices[index - 1])

        return notices

    def _sync_store(self, notices: list[Notice]) -> None:
        """把扫到的通知幂等写入台账，统计结果记到 last_sync。

        说明：先入库后补详情，所以台账里的 content 常常是空的——
        notices 表的定位是"哪些通知见过"的台账，正文核心资产在
        比赛卡片里，这个取舍在 P3 阶段是划算的。
        """
        if self.notice_store is None:
            return
        new_count = existing_count = 0
        for notice in notices:
            if self.notice_store.save_notice_if_absent(notice):
                new_count += 1
            else:
                existing_count += 1
        self.last_sync = {"new": new_count, "existing": existing_count}
