"""scan_site 用例：扫一次官网，产出通知列表（可选补抓若干条详情）。

"用例（use case）"= 一条完整的业务动作，是 application 层的主角。
它只认识 domain/ports.py 里的 NoticeSourcePort 接口，完全不关心
实现是 requests 还是别的什么——所以单元测试时可以塞一个假的
"内存爬虫"，又快又稳。

后面的阶段会扩展这条用例：P2 抓完通知接"LLM 识别比赛"，
P3 识别结果入库。P1 先只负责把通知完整地拿回来。
"""

from __future__ import annotations

from ...domain.entities import Notice
from ...domain.ports import NoticeSourcePort


class ScanSite:
    """扫描一个站点源，返回通知列表。"""

    def __init__(self, source: NoticeSourcePort):
        # 依赖注入：爬虫从外面递进来，本类不自己创建（装配根的纪律）
        self.source = source

    def execute(
        self, limit: int = 10, detail_indexes: list[int] | None = None
    ) -> list[Notice]:
        """执行扫描。

        limit：最多返回多少条通知；
        detail_indexes：需要补抓正文的序号列表（从 1 开始数），
        比如 [1] 表示给第 1 条补抓详情。序号越界会被安全跳过。
        """
        notices = self.source.list_notices(limit=limit)

        # 只对用户点名的条目抓详情——每一条都是一次真实 HTTP 请求，
        # 不点名就不抓，省流量也省时间
        for index in detail_indexes or []:
            if 1 <= index <= len(notices):
                notices[index - 1] = self.source.fetch_detail(notices[index - 1])

        return notices
