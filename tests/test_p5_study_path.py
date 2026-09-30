"""P5 验收测试：搜索解析、引用校验、反馈回路，全程假网络 + 假 runner。

测试重点是 P5 的核心机制——"生成 → 提取网址 → 逐一校验 → 死链反馈重做"：
- Bing 结果解析：对着真实保存的结果页样本测（和 P1 的 fixtures 思路一致）；
- 校验回路：用"可控的假搜索"决定哪些链接算死链，
  验证第一轮有死链时会把清单反馈给第二轮；
- 框架循环本身不测（那是 AgentScope 的责任，v1.5 迁移时的既定分工）。
"""

import asyncio
import os
from pathlib import Path

import pytest

from contest_agent.application.harness.agent_factory import (
    AgentOutcome,
    MaterialTools,
    build_study_tools,
)
from contest_agent.application.usecases.plan_study_path import (
    PlanStudyPath,
    extract_urls,
)
from contest_agent.domain.entities import Competition, Notice
from contest_agent.infrastructure.search.web_search import (
    _parse_bing_results,
    _parse_so360_results,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------- Bing 结果解析（真实页面样本，离线） ----------


def test_parse_bing_results_extracts_items() -> None:
    html = (FIXTURES_DIR / "bing_search.html").read_text(encoding="utf-8")

    results = _parse_bing_results(html)

    assert len(results) == 10  # 真实样本第一页有 10 条
    first = results[0]
    assert first["title"] and first["url"].startswith("http")


def test_parse_so360_results_extracts_real_urls() -> None:
    """360 结果的 href 是跳转链接，真实网址在 data-mdurl 属性里。"""
    html = (FIXTURES_DIR / "so360_search.html").read_text(encoding="utf-8")

    results = _parse_so360_results(html)

    assert len(results) >= 5
    first = results[0]
    assert first["title"]
    assert first["url"].startswith("http")
    assert "so.com/link" not in first["url"]  # 拿到的是真实网址，不是跳转包装


def test_parse_bing_results_skips_items_without_link() -> None:
    html = '<ul><li class="b_algo"><h2>没有链接的条目</h2></li></ul>'

    assert _parse_bing_results(html) == []


# ---------- 网址提取 ----------


def test_extract_urls_dedupes_and_strips_punctuation() -> None:
    markdown = (
        "看这两个：\n"
        "- https://example.com/a，很不错。\n"
        "- https://example.com/a（重复，应去重）\n"
        "- https://example.com/b。\n"
    )

    urls = extract_urls(markdown)

    assert urls == ["https://example.com/a", "https://example.com/b"]


# ---------- 假搜索与假 runner ----------


class FakeSearch:
    """可控的假搜索：search 返回预设结果，check_url 按网址里的关键词判死活。"""

    def __init__(self, results: list[dict]) -> None:
        self._results = results

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        return self._results[:top_k]

    def read_page(self, url: str, max_chars: int = 3000) -> str:
        return f"{url} 的页面正文"

    def check_url(self, url: str) -> tuple[bool, str]:
        if "dead" in url:
            return False, "HTTP 404"
        return True, "正常（HTTP 200）"


class FakeRunner:
    """剧本式假 runner：模拟 agent 的行为（写文件），并记录收到的请求。"""

    def __init__(self, files_per_round: list[dict[str, str]]) -> None:
        # 每一轮 agent"会保存的材料"：{文件名: 内容}
        self._files_per_round = files_per_round
        self.rounds = 0
        self.requests: list[dict] = []

    def __call__(self, **kwargs) -> tuple[AgentOutcome, MaterialTools]:
        self.requests.append(kwargs)
        tools = asyncio.run(kwargs["tools_builder"]())  # 像框架一样构建工具箱
        files = self._files_per_round[min(self.rounds, len(self._files_per_round) - 1)]
        for filename, content in files.items():
            tools.functions["save_material"](filename=filename, content=content)
        self.rounds += 1
        return AgentOutcome(final_text=f"第 {self.rounds} 轮完成", error=None), tools


def _card() -> Competition:
    return Competition(name="蓝桥杯大赛", notice_url="https://x.edu.cn/n1", type="exam")


# ---------- 校验-反馈回路 ----------


def test_dead_links_trigger_feedback_round(tmp_path: Path) -> None:
    """第一轮引用含死链 → 死链清单被反馈进第二轮请求 → 第二轮修好即通过。"""
    search = FakeSearch(results=[])
    # 第一轮引用了一个死链；第二轮修复
    runner = FakeRunner(
        files_per_round=[
            {"study-path.md": "第一阶段看 https://good.example.com 和 https://dead.example.com"},
            {"study-path.md": "第一阶段看 https://good.example.com 和 https://fixed.example.com"},
        ]
    )
    usecase = PlanStudyPath(
        profile=None,  # type: ignore[arg-type] — 假 runner 不会真用档案
        search=search,
        competition_repository=type("R", (), {"list_all": lambda self: [_card()]})(),
        output_dir=tmp_path,
        runner=runner,
    )

    result = usecase.execute()

    assert runner.rounds == 2  # 触发了第二轮
    # 第二轮的请求里必须包含死链反馈
    second_request = runner.requests[1]["user_request"]
    assert "https://dead.example.com" in second_request
    assert "失效" in second_request
    # 最终全部链接通过
    assert result.success is True
    assert all(c["ok"] for c in result.citations)
    assert {c["url"] for c in result.citations} == {
        "https://good.example.com",
        "https://fixed.example.com",
    }


def test_all_valid_links_pass_in_one_round(tmp_path: Path) -> None:
    runner = FakeRunner(
        files_per_round=[
            {"study-path.md": "参考 https://lanqiao.example.com 官网"},
        ]
    )
    usecase = PlanStudyPath(
        profile=None,  # type: ignore[arg-type]
        search=FakeSearch(results=[]),
        competition_repository=type("R", (), {"list_all": lambda self: [_card()]})(),
        output_dir=tmp_path,
        runner=runner,
    )

    result = usecase.execute()

    assert runner.rounds == 1  # 一次通过，不需要反馈轮
    assert result.success is True


def test_picks_exam_type_card_first(tmp_path: Path) -> None:
    """不指定比赛名时，优先选考试型卡片（备考路径的主场景）。"""
    cards = [
        Competition(name="数媒竞赛", notice_url="u1", type="deliverable"),
        Competition(name="蓝桥杯", notice_url="u2", type="exam"),
    ]

    class Repo:
        def list_all(self) -> list[Competition]:
            return cards

    runner = FakeRunner(files_per_round=[{"study-path.md": "https://ok.example.com"}])
    usecase = PlanStudyPath(
        profile=None,  # type: ignore[arg-type]
        search=FakeSearch(results=[]),
        competition_repository=Repo(),
        output_dir=tmp_path,
        runner=runner,
    )

    result = usecase.execute()

    assert result.competition_name == "蓝桥杯"


def test_persists_death_when_rounds_exhausted(tmp_path: Path) -> None:
    """两轮都没修好：如实报失败，不假装成功。"""
    search = FakeSearch(results=[])
    runner = FakeRunner(
        files_per_round=[
            {"study-path.md": "https://dead.example.com"},
            {"study-path.md": "https://dead.example.com"},  # 第二轮还在引用死链
        ]
    )
    usecase = PlanStudyPath(
        profile=None,  # type: ignore[arg-type]
        search=search,
        competition_repository=type("R", (), {"list_all": lambda self: [_card()]})(),
        output_dir=tmp_path,
        runner=runner,
    )

    result = usecase.execute()

    assert result.success is False
    assert any(not c["ok"] for c in result.citations)


# ---------- 真实联网集成测试（默认不跑） ----------


@pytest.mark.live
def test_live_study_path_real_search(tmp_path: Path) -> None:
    """验收标准：真实搜索生成备考路径，全部引用经验证真实存在。

    运行：uv run pytest -m live（需要 .env 密钥，且库里至少有一张卡片）
    """
    from contest_agent.settings import load_dotenv

    load_dotenv()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("未配置 DEEPSEEK_API_KEY")
    from contest_agent.composition import build_plan_study_path_usecase

    result = build_plan_study_path_usecase(output_dir=tmp_path).execute()

    assert result.success is True, f"失败：{result.error}"
    assert len(result.citations) >= 2
    assert all(c["ok"] for c in result.citations)  # 每个引用都真实存在
