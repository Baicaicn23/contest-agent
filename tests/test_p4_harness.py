"""P4 验收测试（v1.5，AgentScope 迁移后）。

迁移后测试对象随之调整：
- 循环本体（ReAct 编排）由 AgentScope 框架负责，框架的代码框架自己测，
  我们不再重复测——这是用框架的正常代价与收益；
- 我们仍然要测的是"接驳层胶水"：工具函数行为对不对（落盘/防穿越/容错）、
  用例编排对不对（提示词拼装、选卡、结果映射）；
- 真实联网生成材料放 live 测试，默认不跑。
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path

import pytest

from contest_agent.application.harness.agent_factory import (
    AgentOutcome,
    MaterialTools,
    build_material_tools,
)
from contest_agent.application.harness.skills import list_skills, load_skill
from contest_agent.application.usecases.generate_material import GenerateMaterial
from contest_agent.domain.entities import Competition, Notice


# ---------- 技能加载 ----------


def test_load_real_skills() -> None:
    assert set(list_skills()) >= {"ppt-outline", "proposal"}

    skill = load_skill("ppt-outline")
    assert skill.description  # frontmatter 里有描述
    assert "save_material" in skill.instructions  # 指令里教了怎么落盘


def test_load_missing_skill_lists_available() -> None:
    with pytest.raises(FileNotFoundError, match="ppt-outline"):
        load_skill("不存在的技能")


# ---------- 工具接驳层（Toolkit 注册 + 原函数行为） ----------


@pytest.fixture
def material_tools(tmp_path: Path) -> MaterialTools:
    """构建真实的工具箱：假爬虫 + 假仓储 + 临时输出目录。"""
    class FakeCrawler:
        def fetch_detail(self, notice: Notice) -> Notice:
            notice.content = "比赛通知正文：评审重点是创新性。"
            return notice

    class FakeRepository:
        def list_all(self) -> list[Competition]:
            return []  # 空库场景由用例层测试覆盖，这里专注工具行为

    return asyncio.run(
        build_material_tools(FakeCrawler(), FakeRepository(), tmp_path)
    )


def test_tools_registered_into_toolkit(material_tools: MaterialTools) -> None:
    """三件工具都注册进了 AgentScope 的 Toolkit，且带上了说明书。"""
    schemas = asyncio.run(material_tools.toolkit.get_tool_schemas())
    names = {s["function"]["name"] for s in schemas}

    assert names == {"list_competitions", "get_notice_content", "save_material"}
    for schema in schemas:
        assert schema["function"]["description"]  # 说明书来自 docstring，不能为空


def test_save_material_tool_writes_file(material_tools: MaterialTools, tmp_path: Path) -> None:
    result = material_tools.functions["save_material"](
        filename="ppt-outline.md", content="# 大纲\n第一页"
    )

    assert "已保存" in result
    assert (tmp_path / "ppt-outline.md").read_text(encoding="utf-8") == "# 大纲\n第一页"
    assert any("save_material" in line for line in material_tools.trace)  # 轨迹被记录


def test_save_material_rejects_path_traversal(material_tools: MaterialTools) -> None:
    result = material_tools.functions["save_material"](
        filename="../evil.md", content="恶意内容"
    )

    assert "不能包含路径" in result  # 返回错误文本给模型，而不是抛异常


def test_save_material_rejects_non_markdown(material_tools: MaterialTools) -> None:
    result = material_tools.functions["save_material"](
        filename="report.exe", content="..."
    )

    assert ".md" in result


def test_get_notice_content_returns_crawler_text(
    material_tools: MaterialTools,
) -> None:
    result = material_tools.functions["get_notice_content"](
        notice_url="https://x.edu.cn/n1"
    )

    assert "评审重点是创新性" in result


def test_list_competitions_empty_gives_hint(material_tools: MaterialTools) -> None:
    result = material_tools.functions["list_competitions"]()

    assert "sai identify" in result  # 空库时给模型可传达的提示


# ---------- 用例编排（假 runner，不碰框架和网络） ----------


class FakeRepository:
    def list_all(self) -> list[Competition]:
        return [
            Competition(
                name="数媒竞赛",
                notice_url="https://x.edu.cn/n1",
                type="deliverable",
                deadline=datetime(2026, 10, 23),
            )
        ]


class FakeCrawler:
    def fetch_detail(self, notice: Notice) -> Notice:
        return notice


class FakeRunner:
    """假 runner：记录收到的装配参数，返回预设结果。"""

    def __init__(self, outcome: AgentOutcome) -> None:
        self.outcome = outcome
        self.kwargs: dict = {}

    def __call__(self, **kwargs) -> tuple[AgentOutcome, MaterialTools]:
        self.kwargs = kwargs
        return self.outcome, MaterialTools(toolkit=None, trace=["list_competitions()"])  # type: ignore[arg-type]


def test_generate_material_orchestrates_prompt_and_result(tmp_path: Path) -> None:
    """编排验收：提示词拼装正确、结果字段映射正确、轨迹透传。"""
    runner = FakeRunner(
        outcome=AgentOutcome(final_text="大纲已生成", error=None)
    )
    usecase = GenerateMaterial(
        profile=None,  # type: ignore[arg-type] — 假 runner 不会真用档案
        source=FakeCrawler(),
        competition_repository=FakeRepository(),
        output_dir=tmp_path,
        runner=runner,
    )

    result = usecase.execute(skill_name="ppt-outline")

    # 提示词装配：系统提示 = 基础守则 + 技能指令；用户消息带齐卡片信息
    assert "工作守则" in runner.kwargs["system_prompt"]
    assert "save_material" in runner.kwargs["system_prompt"]
    assert "数媒竞赛" in runner.kwargs["user_request"]
    assert "2026-10-23" in runner.kwargs["user_request"]

    # 结果映射
    assert result.success is True
    assert result.final_text == "大纲已生成"
    assert result.competition_name == "数媒竞赛"
    assert result.tool_trace == ["list_competitions()"]  # 轨迹透传给 CLI 播报


def test_generate_material_surfaces_error(tmp_path: Path) -> None:
    runner = FakeRunner(
        outcome=AgentOutcome(final_text="任务中断", error="已达最大迭代次数")
    )
    usecase = GenerateMaterial(
        profile=None,  # type: ignore[arg-type]
        source=FakeCrawler(),
        competition_repository=FakeRepository(),
        output_dir=tmp_path,
        runner=runner,
    )

    result = usecase.execute(skill_name="proposal")

    assert result.success is False
    assert result.error == "已达最大迭代次数"


def test_generate_material_rejects_when_no_cards(tmp_path: Path) -> None:
    class EmptyRepository:
        def list_all(self) -> list:
            return []

    usecase = GenerateMaterial(
        profile=None,  # type: ignore[arg-type]
        source=FakeCrawler(),
        competition_repository=EmptyRepository(),
        output_dir=tmp_path,
        runner=FakeRunner(outcome=AgentOutcome(final_text="", error=None)),
    )

    with pytest.raises(RuntimeError, match="sai identify"):
        usecase.execute(skill_name="ppt-outline")


# ---------- 真实联网集成测试（默认不跑） ----------


@pytest.mark.live
def test_live_generate_material_with_agentscope(tmp_path: Path) -> None:
    """验收标准：AgentScope 循环真实为库里最新比赛生成 PPT 大纲并落盘。

    运行：uv run pytest -m live（需要 .env 的 DEEPSEEK_API_KEY 和库里有卡片）
    """
    from contest_agent.settings import load_dotenv

    load_dotenv()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("未配置 DEEPSEEK_API_KEY")
    from contest_agent.composition import build_generate_material_usecase

    result = build_generate_material_usecase(output_dir=tmp_path).execute(
        skill_name="ppt-outline"
    )

    assert result.success is True, f"生成失败：{result.error}"
    assert len(result.tool_trace) >= 2  # 至少查了信息 + 落了盘
    written = tmp_path / "ppt-outline.md"
    assert written.exists()
    assert len(written.read_text(encoding="utf-8")) > 300  # 大纲有实质内容
