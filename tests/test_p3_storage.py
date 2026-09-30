"""P3 验收测试：落库、幂等、可迁移、报告渲染，全程不碰网络不调 LLM。

最重要的两条验收及其考法：
- "重复扫描 0 重复"：同一个仓储存两遍，第二遍全被幂等挡下；
- "换内存库 URL 测试仍通过"：同一套测试逻辑用参数化跑两遍——
  一遍文件库、一遍内存库。业务和仓储代码零改动全绿，
  就是"换 DATABASE_URL 不改代码"承诺的兑现证明。
"""

from datetime import datetime

import pytest

from contest_agent.application.usecases.generate_report import GenerateReport
from contest_agent.application.usecases.identify_competitions import (
    IdentifyCompetitions,
)
from contest_agent.application.usecases.scan_site import ScanSite
from contest_agent.domain.entities import Competition, Notice
from contest_agent.infrastructure.persistence.repository import (
    SqliteCompetitionRepository,
    SqliteNoticeRepository,
    competition_hash,
)


def _sample_card(name: str = "蓝桥杯大赛", notice_url: str = "https://x.edu.cn/n1") -> Competition:
    """造一张标准测试卡片。"""
    return Competition(
        name=name,
        notice_url=notice_url,
        type="exam",
        deadline=datetime(2026, 11, 8),
        evidence="第十七届蓝桥杯大赛报名通知",
    )


@pytest.fixture(params=["file", "memory"])
def competition_repo(request, tmp_path):
    """同一个测试逻辑跑两种连接串：这就是"可迁移性"的考法。"""
    if request.param == "file":
        return SqliteCompetitionRepository(f"sqlite:///{tmp_path}/p3_test.db")
    return SqliteCompetitionRepository("sqlite:///:memory:")


# ---------- 卡片仓储：增查与幂等 ----------


def test_save_and_list_roundtrip(competition_repo) -> None:
    card = _sample_card()

    assert competition_repo.save_if_absent(card) is True  # 首次写入

    cards = competition_repo.list_all()
    assert len(cards) == 1
    assert cards[0].name == "蓝桥杯大赛"
    assert cards[0].type == "exam"
    assert cards[0].deadline == datetime(2026, 11, 8)  # 日期经库里转一圈没变形
    assert cards[0].evidence == "第十七届蓝桥杯大赛报名通知"


def test_save_twice_is_idempotent(competition_repo) -> None:
    """验收核心：重复扫描 0 重复——同一张卡存两遍，库里只有一份。"""
    card = _sample_card()

    assert competition_repo.save_if_absent(card) is True   # 第一遍：新写入
    assert competition_repo.save_if_absent(card) is False  # 第二遍：被幂等挡下
    assert competition_repo.count() == 1


def test_hash_distinguishes_different_cards() -> None:
    """幂等键 = 来源URL + 比赛名：任一不同就是两张卡，互不误伤。"""
    same_notice_diff_name = _sample_card(name="蓝桥杯大赛（软件类）")
    diff_notice_same_name = _sample_card(notice_url="https://x.edu.cn/n2")

    assert competition_hash(_sample_card()) != competition_hash(same_notice_diff_name)
    assert competition_hash(_sample_card()) != competition_hash(diff_notice_same_name)


# ---------- 通知台账仓储 ----------


def test_notice_repository_is_idempotent(tmp_path) -> None:
    repo = SqliteNoticeRepository(f"sqlite:///{tmp_path}/notices.db")
    notice = Notice(source_url="https://x.edu.cn/n1", title="通知一")

    assert repo.save_notice_if_absent(notice) is True
    assert repo.save_notice_if_absent(notice) is False  # 幂等挡下
    assert len(repo.list_notices()) == 1
    assert repo.list_notices()[0].title == "通知一"


def test_repository_creates_missing_directories(tmp_path) -> None:
    """全新克隆回归：数据库文件所在的目录不存在时自动创建（data/ 不进 git）。"""
    deep_url = f"sqlite:///{tmp_path / 'deep' / 'nested' / 'fresh.db'}"

    repo = SqliteCompetitionRepository(deep_url)
    repo.save_if_absent(_sample_card())

    assert repo.count() == 1


# ---------- 用例层：扫描/识别接上仓储后的编排 ----------


class FakeSource:
    """内存假爬虫（和 P1 测试同款思路）。"""

    def __init__(self, notices: list[Notice]) -> None:
        self._notices = notices

    def list_notices(self, limit: int = 10) -> list[Notice]:
        return self._notices[:limit]

    def fetch_detail(self, notice: Notice) -> Notice:
        return notice


class FakeLlm:
    """内存假 LLM：永远返回同一张卡片。"""

    def __init__(self, card: dict) -> None:
        self._card = card
        self.calls = 0

    def complete_structured(self, system: str, user: str, schema: dict | None = None) -> dict:
        self.calls += 1
        return self._card


def test_scan_site_stores_notices_with_stats(tmp_path) -> None:
    """扫描接台账：第一遍全新增，第二遍 0 新增。"""
    repo = SqliteNoticeRepository(f"sqlite:///{tmp_path}/sync.db")
    notices = [Notice(source_url=f"https://x.edu.cn/n{i}", title=f"竞赛通知{i}") for i in range(3)]
    usecase = ScanSite(FakeSource(notices), repo)

    usecase.execute(limit=3)
    assert usecase.last_sync == {"new": 3, "existing": 0}

    usecase.execute(limit=3)  # 同一批通知再扫一遍
    assert usecase.last_sync == {"new": 0, "existing": 3}  # 重复扫描 0 重复


def test_identify_stores_cards_with_stats(tmp_path) -> None:
    """识别接卡片仓储：卡片落库，重复识别不产生第二张。"""
    repo = SqliteCompetitionRepository(f"sqlite:///{tmp_path}/cards.db")
    source = FakeSource([Notice(source_url="https://x.edu.cn/n1", title="蓝桥杯大赛报名通知")])
    llm = FakeLlm(
        card={
            "is_competition": True,
            "name": "蓝桥杯大赛",
            "type": "exam",
            "deadline": "2026-11-08",
            "evidence": "报名通知",
            "reason": "认证考试类",
        }
    )
    usecase = IdentifyCompetitions(source, llm, repo)

    outcomes = usecase.execute(limit=1)
    assert usecase.last_sync == {"new": 1, "existing": 0}
    assert llm.calls == 1

    usecase.execute(limit=1)  # 第二次识别同一批
    assert usecase.last_sync == {"new": 0, "existing": 1}
    assert llm.calls == 2  # LLM 还是会调（判断是新知识），但库里不会多一张卡
    assert repo.count() == 1


# ---------- 报告渲染 ----------


def test_generate_report_renders_markdown(tmp_path) -> None:
    repo = SqliteCompetitionRepository(f"sqlite:///{tmp_path}/report.db")
    repo.save_if_absent(_sample_card())  # 考试型，截止 2026-11-08
    repo.save_if_absent(
        Competition(  # 再造一张交付物型
            name="数媒竞赛",
            notice_url="https://x.edu.cn/n2",
            type="deliverable",
            deadline=datetime(2026, 10, 23),
            evidence="赛程时间：截至2026年10月23日",
        )
    )

    markdown = GenerateReport(repo).execute()

    assert "# 🏆 比赛情报报告" in markdown
    assert "共 2 场比赛" in markdown
    assert "数媒竞赛" in markdown and "蓝桥杯大赛" in markdown
    assert "交付物型" in markdown and "考试型" in markdown
    assert "2026-10-23" in markdown  # 截止日期进了表格
    assert "赛程时间：截至2026年10月23日" in markdown  # 原文证据进了复核区
    # 排序：截止早的数媒竞赛（10-23）应排在蓝桥杯（11-08）前面
    assert markdown.index("数媒竞赛") < markdown.index("蓝桥杯大赛")


def test_generate_report_empty_repository(tmp_path) -> None:
    repo = SqliteCompetitionRepository(f"sqlite:///{tmp_path}/empty.db")
    markdown = GenerateReport(repo).execute()

    assert "暂无已识别的比赛" in markdown
