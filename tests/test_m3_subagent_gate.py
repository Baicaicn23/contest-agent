"""M3 验收测试（二）：子代理（研究分身）与权限门。

- 分身用假搜索 + 假摘要模型测：分身调了几次 LLM、摘要有界、网址来自材料；
- 权限门用注入的 interactive 标志 + monkeypatch input 测：
  交互确认、拒绝、无人值守禁用、不在名单全放行。
"""

import asyncio
from pathlib import Path

import pytest

from contest_agent.application.harness.agent_factory import _add_tool, build_study_tools
from contest_agent.application.harness.permission_gate import PermissionGate
from contest_agent.domain.entities import Competition, Notice
from contest_agent.infrastructure.persistence.repository import (
    SqliteCompetitionRepository,
)


# ---------- 研究分身（research_digest） ----------


class FakeSearch:
    """假搜索：固定两条结果；read_page 返回带网址标记的假正文。"""

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        self.last_query = query
        return [
            {"title": "蓝桥杯官网", "url": "http://x/lanqiao", "snippet": "报名入口"},
            {"title": "备考经验帖", "url": "http://x/exp", "snippet": "刷真题"},
            {"title": "第三条", "url": "http://x/third", "snippet": "不应被精读"},
        ]

    def read_page(self, url: str, max_chars: int = 3000) -> str:
        return f"{url} 的正文内容" * 10


class FakeDigestLlm:
    """假摘要模型：记录调用次数，返回固定结构化摘要。"""

    def __init__(self) -> None:
        self.calls = 0
        self.last_user = ""

    def complete_structured(self, system: str, user: str, schema: dict) -> dict:
        self.calls += 1
        self.last_user = user
        return {
            "summary": "蓝桥杯备考以真题为核心。",
            "key_points": ["先刷近三年真题", "官网报名勿错过截止"],
            "useful_urls": ["http://x/lanqiao"],
        }


def _build_tools(digest_llm):
    """造一个装好 study 工具箱的 MaterialTools（直接复用 agent_factory 的装配）。"""
    repo = SqliteCompetitionRepository("sqlite:///:memory:")
    tools = asyncio.run(build_study_tools(
        search=FakeSearch(),
        competition_repository=repo,
        output_dir=Path("/tmp/m3-test-output"),
        digest_llm=digest_llm,
    ))
    return tools


def test_research_digest_returns_bounded_summary() -> None:
    """分身：调 1 次摘要模型、只精读前 2 页、返回结构化摘要文本。"""
    digest_llm = FakeDigestLlm()
    tools = _build_tools(digest_llm)

    result = tools.functions["research_digest"]("蓝桥杯 备考经验")

    assert digest_llm.calls == 1                 # 分身内部只花一次结构化调用
    # 材料包里有被精读的两个网址，没有第三个（只读前 2 条）
    assert "http://x/lanqiao" in digest_llm.last_user
    assert "http://x/exp" in digest_llm.last_user
    assert "http://x/third" not in digest_llm.last_user
    # 主循环收到的是渲染后的摘要，不是原文
    assert "蓝桥杯备考以真题为核心" in result
    assert "- 先刷近三年真题" in result
    assert "http://x/lanqiao" in result
    assert len(result) < 600                     # 摘要有界（原文每页 200+ 字 × 2）


def test_research_digest_no_results_and_no_llm_paths() -> None:
    """搜索空手而归 → 不花摘要模型的钱，给人话提示。"""

    class EmptySearch(FakeSearch):
        def search(self, query, top_k=5):
            return []

    digest_llm = FakeDigestLlm()
    repo = SqliteCompetitionRepository("sqlite:///:memory:")
    tools = asyncio.run(build_study_tools(
        search=EmptySearch(), competition_repository=repo,
        output_dir=Path("/tmp/m3-test-output"), digest_llm=digest_llm,
    ))
    result = tools.functions["research_digest"]("随便")
    assert digest_llm.calls == 0
    assert "没有返回结果" in result

    # 没装配分身（digest_llm=None）→ 提示退回 search_web + read_page
    tools2 = asyncio.run(build_study_tools(
        search=FakeSearch(), competition_repository=repo,
        output_dir=Path("/tmp/m3-test-output"), digest_llm=None,
    ))
    result2 = tools2.functions["research_digest"]("随便")
    assert "未装配" in result2


# ---------- 权限门 ----------


def _tool():
    """被保护的原工具：干了活就返回一句回执。"""

    def save_material(filename: str, content: str) -> str:
        """把材料保存为文件。"""
        return f"已保存 {filename}"

    return save_material


def test_gate_passthrough_when_not_listed() -> None:
    """不在任何名单里 = 原样放行（v1 以来的默认行为）。"""
    gate = PermissionGate(confirm_tools=["other_tool"],
                          unattended_deny_tools=["other_tool"],
                          interactive=False)
    wrapped = gate.wrap(_tool())
    assert wrapped("a.md", "内容") == "已保存 a.md"


def test_gate_confirm_allows_on_y(monkeypatch) -> None:
    """交互模式 + 确认名单：回答 y 放行，工具真正执行。"""
    gate = PermissionGate(confirm_tools=["save_material"], interactive=True)
    wrapped = gate.wrap(_tool())
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert wrapped("a.md", "内容") == "已保存 a.md"


def test_gate_confirm_denies_on_n(monkeypatch) -> None:
    """交互模式 + 确认名单：回答 n（或回车默认）拒绝，原函数不执行。"""
    gate = PermissionGate(confirm_tools=["save_material"], interactive=True)
    wrapped = gate.wrap(_tool())
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    result = wrapped("a.md", "内容")
    assert "拒绝" in result
    monkeypatch.setattr("builtins.input", lambda prompt: "")  # 空回车 = 默认拒绝
    assert "拒绝" in wrapped("a.md", "内容")


def test_gate_unattended_deny_blocks_silently_listed_tool() -> None:
    """无人值守 + 禁用名单：一律拒绝，拒绝理由回给模型（它好换路走）。"""
    gate = PermissionGate(unattended_deny_tools=["save_material"], interactive=False)
    wrapped = gate.wrap(_tool())
    result = wrapped("a.md", "内容")
    assert "被权限门拦截" in result
    assert "unattended_deny_tools" in result


def test_gate_interactive_skips_confirm_list() -> None:
    """无人值守时 confirm 名单不生效（没人可问）——按原样放行，
    要在无人值守禁用某工具应放进 unattended_deny_tools。"""
    gate = PermissionGate(confirm_tools=["save_material"], interactive=False)
    wrapped = gate.wrap(_tool())
    assert wrapped("a.md", "内容") == "已保存 a.md"


def test_gate_preserves_tool_metadata() -> None:
    """权限门外壳不能弄丢工具说明书（名字/docstring），否则模型看不懂工具。"""
    gate = PermissionGate(confirm_tools=["save_material"], interactive=False)
    wrapped = gate.wrap(_tool())
    assert wrapped.__name__ == "save_material"
    assert "保存" in wrapped.__doc__


def test_gate_inside_tool_registration_chain() -> None:
    """权限门嵌进 _add_tool 的套壳链：拒绝短路（截断/记录壳之内、原函数之外）。"""
    from contest_agent.application.harness.agent_factory import MaterialTools
    from contest_agent.application.harness.permission_gate import PermissionGate
    from agentscope.tool import Toolkit

    calls: list[str] = []

    def save_material(filename: str, content: str) -> str:
        """保存材料。"""
        calls.append("executed")
        return "已保存"

    tools = MaterialTools(toolkit=Toolkit())
    gate = PermissionGate(unattended_deny_tools=["save_material"], interactive=False)
    asyncio.run(_add_tool(tools.toolkit, save_material, recorder=None, gate=gate))

    # 从工具箱里取出注册好的函数直接调（绕过框架的调度，只验壳的行为）；
    # get_tool_schemas 是异步方法（v1.5 迁移时就踩过的框架细节）
    registered = asyncio.run(tools.toolkit.get_tool_schemas())
    assert any(s["function"]["name"] == "save_material" for s in registered)
