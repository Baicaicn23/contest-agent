"""爬虫：requests + BeautifulSoup 实现 NoticeSourcePort（P1 核心模块）。

这个类只负责两件事：
1. 按配置发 HTTP 请求，把网页 HTML 拿回来（限速、重试都在这一步）；
2. 把 HTML 交给 parser.py 里的纯解析函数，换回结构化的 Notice 对象。

为什么限速、重试放在这里而不放 parser？——它们是"网络行为"，
跟 HTML 长什么样无关；parser 只管文本进文本出。职责分清了，
测试解析器才不需要真的上网。
"""

from __future__ import annotations

import time
from urllib.parse import urljoin

import requests

from ...domain.entities import Notice
from ...settings import SourceConfig
from . import parser

# 请求头：很多网站会拒绝没有 User-Agent 的请求（默认的 python-requests 像机器人）。
# 如实表明身份和用途，是对目标网站的礼貌，也更不容易被封。
# 注意：HTTP 头只能用英文/ASCII 字符——头里写中文会直接抛编码异常（P1 真实踩坑）
DEFAULT_HEADERS = {
    "User-Agent": "contest-agent/0.1 (personal study tool; fetching public notices)",
}
TIMEOUT_SECONDS = 15        # 单次请求最多等多久
MAX_RETRIES = 2             # 失败后最多重试几次（不含第一次）
RETRY_WAIT_SECONDS = 2      # 第一次重试前等多久（之后逐次翻倍）


class RequestsNoticeSource:
    """用 requests 抓取配置好的站点源，实现 domain/ports.py 里的 NoticeSourcePort。"""

    def __init__(self, source: SourceConfig):
        self.source = source
        self._last_request_at = 0.0  # 上次请求的时间戳，限速用

    # ---------- 端口要求的两个能力 ----------

    def list_notices(self, limit: int = 10) -> list[Notice]:
        """抓通知列表页（需要更多就翻页），返回最新 limit 条通知。"""
        notices: list[Notice] = []
        page = 1
        while len(notices) < limit:
            html = self._get_html(self._list_page_url(page))
            page_notices = parser.parse_list_page(
                html, self.source.base_url, self.source.selectors
            )
            if not page_notices:
                break  # 这一页一条都没解析出来：可能翻到头了，就此打住
            notices.extend(page_notices)
            page += 1
        return notices[:limit]

    def fetch_detail(self, notice: Notice) -> Notice:
        """去通知的详情页把正文、附件补全，返回同一个对象。"""
        html = self._get_html(notice.source_url)
        return parser.parse_detail_page(
            html, self.source.base_url, self.source.selectors, notice
        )

    # ---------- 内部方法：全是网络行为 ----------

    def _list_page_url(self, page: int) -> str:
        """拼出第 page 页列表页的网址。

        这套网站（博达 CMS）的翻页规律：第 1 页就是列表目录本身，
        第 2 页起是目录后拼 index_2.shtml、index_3.shtml……
        """
        list_url = urljoin(self.source.base_url, self.source.list_path)
        if page <= 1:
            return list_url
        return list_url + f"index_{page}.shtml"

    def _get_html(self, url: str) -> str:
        """下载一个页面，返回 HTML 文本。失败重试，重试耗尽才报错。"""
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._polite_wait()  # 每次请求前都先看限速表
            try:
                resp = requests.get(
                    url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SECONDS
                )
                resp.raise_for_status()  # 4xx/5xx 状态码会在这里抛异常
                # 有些服务器不声明编码， apparent_encoding 让 requests 按内容猜，
                # 猜不出就兜底 utf-8——中文网站编码错了会拿到满屏乱码
                resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            except requests.RequestException as error:
                # 网络抖动、超时都很常见：记下原因，等一会再试
                # 等待时间随尝试次数翻倍（2s、4s……），给对方喘息机会
                last_error = error
                time.sleep(RETRY_WAIT_SECONDS * attempt)
        raise ConnectionError(
            f"抓取失败（已重试 {MAX_RETRIES} 次）：{url}；最后一次原因：{last_error}"
        )

    def _polite_wait(self) -> None:
        """限速：保证相邻两次请求至少间隔 request_interval 秒。

        这是爬虫的礼貌也是合规要求（开发文档 §11）：
        人家免费给你看数据，别一秒钟抽人家十几个请求。
        """
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.source.request_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()
