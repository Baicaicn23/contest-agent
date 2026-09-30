"""P1 验收测试：爬虫的解析器对着真实页面样本测，全程不碰网络。

tests/fixtures/ 里的三个 HTML 是 2026-09-30 从真实网站保存下来的：
- list_page.html        通知公告列表页（第 1 页，8 条）
- list_page_broken.html 同上，但第一条被故意删掉了标题（测逐条容错）
- detail_page.html      一条竞赛通知的详情页

这样测试又快又稳：解析逻辑变了、网站改版了，测试都会立刻告诉我们。
真实联网的集成测试单独放在文件末尾，标了 @pytest.mark.live，
平时不跑（见 pyproject 的 addopts），验收时用 `uv run pytest -m live` 显式跑。
"""

from datetime import datetime
from pathlib import Path

import pytest

from contest_agent.application.usecases.scan_site import ScanSite
from contest_agent.domain.entities import Notice
from contest_agent.infrastructure.crawler import parser
from contest_agent.infrastructure.crawler.notice_source import RequestsNoticeSource
from contest_agent.settings import load_yaml_config

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _selectors() -> dict[str, str]:
    """用真实 config.yaml 里的选择器跑测试：配置改错了，测试立刻红。"""
    return load_yaml_config().sources[0].selectors


# ---------- 列表页解析 ----------


def test_parse_list_page_extracts_all_items() -> None:
    notices = parser.parse_list_page(
        _read_fixture("list_page.html"), "https://www.cupk.edu.cn", _selectors()
    )

    # 真实列表页第 1 页是 8 条
    assert len(notices) == 8

    first = notices[0]
    assert "数字媒体科技作品及创意竞赛" in first.title
    assert first.published_at == datetime(2026, 9, 29)
    # 相对路径必须被拼成完整网址
    assert first.source_url == "https://www.cupk.edu.cn/szxy/c/2026-09-29/538891.shtml"


def test_parse_list_page_skips_broken_items() -> None:
    """第一条被删了标题，正确行为是跳过它、保住其余 7 条。"""
    notices = parser.parse_list_page(
        _read_fixture("list_page_broken.html"), "https://www.cupk.edu.cn", _selectors()
    )

    assert len(notices) == 7
    # 保留下来的第一条，应该原本是列表里的第二条
    assert "学业状况审核" in notices[0].title


# ---------- 详情页解析 ----------


def test_parse_detail_page_extracts_title_and_content() -> None:
    # 模拟从列表页传来的半成品通知
    notice = parser.parse_detail_page(
        _read_fixture("detail_page.html"),
        "https://www.cupk.edu.cn",
        _selectors(),
        Notice(
            source_url="https://www.cupk.edu.cn/szxy/c/2026-09-29/538891.shtml",
            title="列表页的旧标题（应被详情页标题覆盖）",
        ),
    )

    # 标题被详情页的完整标题覆盖
    assert notice.title == "关于组织参加2026第十四届全国大学生数字媒体科技作品及创意竞赛的通知"
    # 正文是干净纯文本：包含章节文字，且不含 HTML 标签
    assert "三、参赛团队" in notice.content
    assert "<p" not in notice.content and "微软雅黑" not in notice.content
    # 附件列表是列表类型即可（这条真实通知没有文件附件）
    assert isinstance(notice.attachments, list)


# ---------- 限速器 ----------


def test_polite_wait_sleeps_to_keep_interval(monkeypatch) -> None:
    """限速器：上次请求刚发过、间隔没到时，应该 sleep 补足剩余时间。"""
    source_config = load_yaml_config().sources[0]
    crawler = RequestsNoticeSource(source_config)

    now = 1000.0  # 假装的当前时间
    slept: list[float] = []
    monkeypatch.setattr("contest_agent.infrastructure.crawler.notice_source.time.monotonic", lambda: now)
    monkeypatch.setattr(
        "contest_agent.infrastructure.crawler.notice_source.time.sleep",
        lambda seconds: slept.append(seconds),
    )

    # 场景一：0.5 秒前刚请求过，间隔要求 1.5 秒 -> 应补睡 1.0 秒
    crawler._last_request_at = now - 0.5
    crawler._polite_wait()
    assert slept == [1.0]

    # 场景二：距上次请求已经 5 秒，早就超过间隔 -> 不应该睡
    slept.clear()
    crawler._last_request_at = now - 5.0
    crawler._polite_wait()
    assert slept == []


# ---------- 用例层：用假爬虫测编排逻辑（不碰网络） ----------


class FakeNoticeSource:
    """内存假爬虫：实现和 NoticeSourcePort 一模一样的两个方法。

    造假的不是为了省流量，而是为了让用例层的测试只关心
    "编排对不对"（先列表后详情、序号越界安全跳过），
    不掺任何网络因素。
    """

    def __init__(self):
        self.detail_calls: list[str] = []

    def list_notices(self, limit: int = 10) -> list:
        return [
            Notice(source_url=f"https://example.edu.cn/n{i}", title=f"通知{i}")
            for i in range(1, min(limit, 5) + 1)
        ]

    def fetch_detail(self, notice):
        self.detail_calls.append(notice.source_url)
        notice.content = f"{notice.title}的正文"
        return notice


def test_scan_site_usecase_orchestration() -> None:
    fake = FakeNoticeSource()
    usecase = ScanSite(fake)

    notices = usecase.execute(limit=3, detail_indexes=[1, 99])

    assert len(notices) == 3
    assert notices[0].content == "通知1的正文"          # 点名了的第 1 条抓了详情
    assert notices[1].content == ""                     # 没点名的没抓
    assert fake.detail_calls == ["https://example.edu.cn/n1"]  # 99 号越界被安全跳过


# ---------- 真实联网集成测试（默认不跑） ----------


@pytest.mark.live
def test_live_scan_real_site() -> None:
    """验收标准：真实抓取最新 10 条，第 1 条能取到详情正文。

    运行：uv run pytest -m live（需要能直连 www.cupk.edu.cn）
    """
    from contest_agent.composition import build_scan_usecase

    notices = build_scan_usecase().execute(limit=10, detail_indexes=[1])

    assert len(notices) == 10
    assert all(n.title and n.source_url for n in notices)
    assert len(notices[0].content) > 50  # 详情正文不是空的
