"""P4 验收测试：注册表、ReAct 循环、技能加载、材料落盘，全程假 LLM 零成本。

测试的核心是"循环编排对不对"：
- 模型发起工具调用 -> 工具真的被执行 -> 结果回传 -> 模型收尾；
- 工具报错不会崩循环（错误文本回传给模型）；
- 步数耗尽会强制停车并如实报告失败。
真实联网生成材料的集成测试在文件末尾，标 live，默认不跑。
"""

from pathlib import Path

import pytest

import os

from contest_agent.application.harness.loop import AgentRunner
from contest_agent.application.harness.registry import Tool, ToolRegistry
from contest_agent.application.harness.skills import list_skills, load_skill
from contest_agent.application.usecases.generate_material import GenerateMaterial
from contest_agent.domain.entities import LlmReply, ToolCall


# ---------- 假对象 ----------


class FakeLlm:
    """剧本式假 LLM：按预设顺序吐 LlmReply，并记录每次收到的完整消息历史。"""

    def __init__(self, replies: list[LlmReply]) -> None:
        self._replies = list(replies)
        self.histories: list[list[dict]] = []

    def chat_with_tools(self, messages: list[dict], tools: list[dict]) -> LlmReply:
        self.histories.append([dict(m) for m in messages])  # 拷贝存档
        return self._replies.pop(0)

    def complete_structured(self, system: str, user: str, schema: dict) -> dict:
        raise AssertionError("循环引擎不该调用 complete_structured")


# ---------- 工具注册表 ----------


def test_registry_translates_to_openai_schema() -> None:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo",
            description="原样返回文本",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            func=lambda text: text,
        )
    )

    schemas = registry.openai_schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "echo"
    assert schemas[0]["function"]["parameters"]["required"] == ["text"]


def test_registry_call_executes_and_returns_string() -> None:
    registry = ToolRegistry()
    registry.register(Tool("add", "加法", {"type": "object"}, func=lambda a=0, b=0: str(a + b)))

    assert registry.call("add", {"a": 1, "b": 2}) == "3"


def test_registry_unknown_tool_returns_error_text() -> None:
    registry = ToolRegistry()
    result = registry.call("不存在的工具", {})

    # 关键行为：不抛异常，返回错误文本（给模型看并自行纠正）
    assert "不存在" in result and "可用工具" in result


def test_registry_tool_crash_returns_error_text() -> None:
    def boom() -> str:
        raise ValueError("数据库炸了")

    registry = ToolRegistry()
    registry.register(Tool("boom", "会炸的工具", {"type": "object"}, func=boom))

    result = registry.call("boom", {})
    assert "工具执行出错" in result and "数据库炸了" in result


# ---------- ReAct 循环 ----------


def test_loop_executes_tool_then_finishes() -> None:
    """剧本：第一轮调工具，第二轮收尾。验证消息协议与结果组装。"""
    llm = FakeLlm(
        replies=[
            # 第一轮：模型要调工具
            LlmReply(
                content=None,
                tool_calls=[ToolCall(id="call-1", name="echo", arguments={"text": "你好"})],
            ),
            # 第二轮：模型看到工具结果后收尾
            LlmReply(content="任务完成", tool_calls=[]),
        ]
    )
    registry = ToolRegistry()
    registry.register(Tool("echo", "原样返回", {"type": "object"}, func=lambda text: f"回声：{text}"))

    result = AgentRunner(llm, registry, system_prompt="测试").run("跑一次")

    assert result.success is True
    assert result.final_text == "任务完成"
    assert len(result.steps) == 2
    assert result.steps[0].tool_calls[0]["result"] == "回声：你好"

    # 消息协议：第二轮请求的历史里，应该有 assistant(tool_calls) 和 tool 结果
    second_history = llm.histories[1]
    roles = [m["role"] for m in second_history]
    assert roles == ["system", "user", "assistant", "tool"]
    assert second_history[2]["tool_calls"][0]["id"] == "call-1"
    assert second_history[3]["tool_call_id"] == "call-1"
    assert "回声：你好" in second_history[3]["content"]


def test_loop_feeds_tool_error_back_to_model() -> None:
    """工具报错不崩循环：错误文本作为工具结果回传，模型继续。"""

    def boom() -> str:
        raise ValueError("坏了")

    registry = ToolRegistry()
    registry.register(Tool("boom", "会炸", {"type": "object"}, func=boom))

    llm = FakeLlm(
        replies=[
            LlmReply(tool_calls=[ToolCall(id="c1", name="boom", arguments={})]),
            LlmReply(content="看到报错了，已放弃该方案"),
        ]
    )
    result = AgentRunner(llm, registry, system_prompt="测试").run("跑")

    assert result.success is True
    assert "坏了" in llm.histories[1][3]["content"]  # 错误原文被模型看到


def test_loop_stops_at_max_steps() -> None:
    """防呆验收：模型无限调工具时，到站强制停车并如实报告失败。"""
    registry = ToolRegistry()
    registry.register(Tool("noop", "空操作", {"type": "object"}, func=lambda: "ok"))
    # 无限剧本：永远要调工具（pop 空了就重复最后一个）
    endless = LlmReply(tool_calls=[ToolCall(id="x", name="noop", arguments={})])
    llm = FakeLlm(replies=[endless] * 10)

    result = AgentRunner(llm, registry, system_prompt="测试", max_steps=3).run("跑")

    assert result.success is False
    assert len(result.steps) == 3
    assert "最大步数" in result.final_text


# ---------- 技能加载 ----------


def test_load_real_skills() -> None:
    assert set(list_skills()) >= {"ppt-outline", "proposal"}

    skill = load_skill("ppt-outline")
    assert skill.description  # frontmatter 里有描述
    assert "save_material" in skill.instructions  # 指令里教了怎么落盘


def test_load_missing_skill_lists_available() -> None:
    with pytest.raises(FileNotFoundError, match="ppt-outline"):
        load_skill("不存在的技能")


# ---------- 材料生成用例（假 LLM + 真工具 + 临时输出目录） ----------


class FakeRepository:
    """内存卡片仓储（只含用例用到的 list_all）。"""

    def list_all(self) -> list:
        from contest_agent.domain.entities import Competition

        return [
            Competition(
                name="数媒竞赛", notice_url="https://x.edu.cn/n1", type="deliverable"
            )
        ]

    def save_if_absent(self, competition) -> bool:  # pragma: no cover — 本文件不测
        return True


class FakeCrawler:
    """假爬虫：fetch_detail 返回固定正文。"""

    def fetch_detail(self, notice):
        notice.content = "比赛通知正文：评审重点是创新性。"
        return notice


def test_generate_material_writes_file(tmp_path: Path) -> None:
    llm = FakeLlm(
        replies=[
            LlmReply(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="save_material",
                        arguments={"filename": "ppt-outline.md", "content": "# 大纲\n第一页"},
                    )
                ]
            ),
            LlmReply(content="大纲已保存到 ppt-outline.md"),
        ]
    )
    usecase = GenerateMaterial(
        llm=llm,
        source=FakeCrawler(),
        competition_repository=FakeRepository(),
        output_dir=tmp_path,
    )

    result = usecase.execute(skill_name="ppt-outline")

    assert result.success is True
    assert result.competition_name == "数媒竞赛"
    assert any("save_material" in line for line in result.tool_trace)  # 轨迹可播报
    written = tmp_path / "ppt-outline.md"
    assert written.exists()
    assert "# 大纲" in written.read_text(encoding="utf-8")


def test_generate_material_rejects_when_no_cards(tmp_path: Path) -> None:
    class EmptyRepository:
        def list_all(self) -> list:
            return []

    usecase = GenerateMaterial(
        llm=FakeLlm(replies=[]),
        source=FakeCrawler(),
        competition_repository=EmptyRepository(),
        output_dir=tmp_path,
    )

    with pytest.raises(RuntimeError, match="sai identify"):
        usecase.execute(skill_name="ppt-outline")


# ---------- 真实联网集成测试（默认不跑） ----------


@pytest.mark.live
def test_live_generate_material(tmp_path: Path) -> None:
    """验收标准：真实为库里最新的比赛生成 PPT 大纲，文件落盘且有实质内容。

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

    assert result.success is True
    assert result.steps >= 2  # 至少经历"调工具 + 收尾"
    written = tmp_path / "ppt-outline.md"
    assert written.exists()
    content = written.read_text(encoding="utf-8")
    assert len(content) > 300  # 大纲有实质内容，不是一句话交差
