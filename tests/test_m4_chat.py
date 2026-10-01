"""M4 差异化改造验收测试：聊天区背后的真 agent。

- ChatService 编排层：假 agent_runner（逐帧产出）测存档/历史窗口/错误帧；
- 真工具循环：FakeChatModel（M1 的手法）+ 真 Toolkit——模型第一轮调工具、
  第二轮收尾，验证工具帧/逐字帧/最终回复的完整链路；
- SSE 端点用假服务测翻译层。
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from contest_agent.application.cost import BudgetExceededError, CostMeter
from contest_agent.application.usecases.chat_service import ChatService
from contest_agent.domain.entities import UsageEntry
from contest_agent.infrastructure.persistence.repository import (
    SqliteCompetitionRepository,
    SqliteSessionRepository,
    SqliteUsageRepository,
)
from contest_agent.presentation.server import Usecases, create_app
from contest_agent.settings import ModelProfile, load_settings


# ---------- 假对象 ----------


class FakeArchive(SqliteSessionRepository):
    """内存存档（继承真实现，省得手写 CRUD）。"""


def fake_agent_runner(frames_by_call=None, tool_frame=None):
    """造一个假 agent_runner：按调用次序产出预设帧序列，并记录入参。

    frames_by_call[i] = 第 i 次调用产出的帧列表；超出则复用最后一组。
    """
    calls: list[dict] = []
    state = {"n": 0}

    async def runner(session_id, system_prompt, history, user_text):
        calls.append({
            "session_id": session_id,
            "system_prompt": system_prompt,
            "history": list(history),
            "user_text": user_text,
        })
        idx = min(state["n"], (len(frames_by_call) - 1) if frames_by_call else 0)
        state["n"] += 1

        async def gen():
            for frame in frames_by_call[idx]:
                yield frame

        return gen()

    runner.calls = calls
    return runner


# ---------- ChatService 编排层 ----------


def test_chat_service_round_writes_events_and_streams() -> None:
    archive = FakeArchive("sqlite:///:memory:")
    runner = fake_agent_runner([
        [{"type": "tool", "name": "list_competitions"},
         {"type": "token", "text": "库里有"},
         {"type": "token", "text": "3 场比赛"},
         {"type": "done", "reply": "库里有3场比赛"}],
    ])
    service = ChatService(archive, agent_runner=runner, model_name="t-chat")

    session_id = service.open_session()
    chunks = asyncio.run(_collect(service.stream_reply(session_id, "库里有几场比赛")))

    assert [c["type"] for c in chunks] == ["tool", "token", "token", "done"]
    assert chunks[-1]["reply"] == "库里有3场比赛"

    # 轨迹：user_input / tool_call / result 全留档（回放可见 agent 干了什么）
    _, events = archive.get_session(session_id)
    kinds = [e.kind for e in events]
    assert kinds == ["user_input", "tool_call", "result"]
    assert events[1].payload["tool"] == "list_competitions"
    assert events[2].payload["final_text"] == "库里有3场比赛"


async def _collect(agen):
    return [chunk async for chunk in agen]


def test_chat_service_history_window_and_prompt() -> None:
    """多轮上下文窗口 + 系统提示词注入实时数据。"""
    archive = FakeArchive("sqlite:///:memory:")
    usage = SqliteUsageRepository("sqlite:///:memory:")
    usage.record(UsageEntry("chat", "deepseek", "deepseek-chat", 100, 10, 0.00028,
                            created_at=datetime.now()))

    runner = fake_agent_runner([[{"type": "done", "reply": "ok"}],
                                [{"type": "done", "reply": "ok"}]])
    service = ChatService(archive, usage_repository=usage,
                          agent_runner=runner, model_name="t-chat")
    service.competition_repository = None

    session_id = service.open_session()
    for i in range(8):
        asyncio.run(_collect(service.stream_reply(session_id, f"消息{i}")))

    asyncio.run(_collect(service.stream_reply(session_id, "第 9 问")))

    last = runner.calls[-1]
    assert len(last["history"]) == 12               # 6 轮 × 2 条
    assert "t-chat" in last["system_prompt"]
    assert "0.0003" in last["system_prompt"]        # 今日花费注入（保留 4 位）


def test_chat_service_error_frame_recorded() -> None:
    archive = FakeArchive("sqlite:///:memory:")
    runner = fake_agent_runner([
        [{"type": "done", "reply": "", "error": "预算熔断：已达上限"}],
    ])
    service = ChatService(archive, agent_runner=runner)

    session_id = service.open_session()
    chunks = asyncio.run(_collect(service.stream_reply(session_id, "hi")))

    assert chunks[-1]["type"] == "error"
    _, events = archive.get_session(session_id)
    assert events[-1].kind == "error"


# ---------- 真工具循环（FakeChatModel + 真 Toolkit） ----------


class FakeChatModel:
    """鸭子类型假模型：第一轮调 list_competitions，第二轮收尾。

    context_size 故意给大值（不经压缩）；经 MeteredChatModel 包裹后
    连同计价器一起走真的 agent 循环。
    """

    context_size = 100_000
    stream = False
    model = "fake-model"
    formatter = SimpleNamespace(supported_input_media_types=["image/*"])

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, messages, tools=None, **kwargs):
        from agentscope.message import TextBlock, ToolCallBlock
        from agentscope.model import ChatResponse, ChatUsage

        self.calls += 1
        if self.calls == 1:
            return ChatResponse(
                content=[ToolCallBlock(id="c1", name="list_competitions", input="{}")],
                is_last=True,
                usage=ChatUsage(input_tokens=50, output_tokens=5, time=0.01),
            )
        return ChatResponse(
            content=[TextBlock(type="text", text="库里有卡片，我念给你听。")],
            is_last=True,
            usage=ChatUsage(input_tokens=80, output_tokens=10, time=0.01),
        )

    async def count_tokens(self, messages, tools=None) -> int:
        return 50

    async def generate_structured_output(self, *args, **kwargs):
        raise AssertionError("聊天不应触发结构化输出")


def test_real_agent_loop_emits_tool_and_token_frames(tmp_path: Path, monkeypatch) -> None:
    """真 agent 循环端到端（离线）：假模型调真工具 → 工具帧 + 逐字帧 + 完成。"""
    monkeypatch.setenv("K", "fake-key")             # 模型档案构造时的密钥检查
    from contest_agent.application.harness.agent_factory import (
        build_chat_tools,
        run_chat_agent_stream,
    )

    class Repo:
        def save_if_absent(self, competition):
            return True

        def list_all(self):
            return [type("C", (), {"name": "测试杯", "type": "exam",
                                   "deadline": None, "notice_url": "u1"})()]

    async def build():
        return await build_chat_tools(
            source=None, notice_repository=None,
            competition_repository=Repo(), search=None,
            identify_usecase=None, sentinel=None,
        )

    tools = asyncio.run(build())
    profile = ModelProfile(name="t", base_url="https://x", api_key_env="K", model="t")
    meter = CostMeter(profile=profile, task_type="chat")

    async def run():
        return [f async for f in run_chat_agent_stream(
            profile, meter, "你是测试助手", [], "库里有比赛吗", tools,
            model=FakeChatModel())]

    frames = asyncio.run(run())

    types = [f["type"] for f in frames]
    assert "tool" in types and "token" in types
    tool_frame = next(f for f in frames if f["type"] == "tool")
    assert tool_frame["name"] == "list_competitions"  # 模型真的发起了查卡片调用
    done = frames[-1]
    assert done["type"] == "done"
    assert "念给你听" in done["reply"]
    assert meter.call_count == 2                    # 两轮模型调用都过了计价器


def test_real_agent_loop_budget_break(tmp_path: Path, monkeypatch) -> None:
    """预算熔断：模型调用前被计价器拦下，循环以 error 收场。"""
    monkeypatch.setenv("K", "fake-key")
    from contest_agent.application.harness.agent_factory import (
        build_chat_tools,
        run_chat_agent_stream,
    )

    async def build():
        return await build_chat_tools(
            source=None, notice_repository=None,
            competition_repository=SqliteCompetitionRepository("sqlite:///:memory:"),
            search=None, identify_usecase=None, sentinel=None,
        )

    tools = asyncio.run(build())
    profile = ModelProfile(name="t", base_url="https://x", api_key_env="K", model="t")

    class BrokenMeter:
        def precheck(self):
            raise BudgetExceededError("预算熔断：已达上限")

        def record(self, **kwargs):
            pass

    async def run():
        return [f async for f in run_chat_agent_stream(
            profile, BrokenMeter(), "s", [], "hi", tools,
            model=FakeChatModel())]

    frames = asyncio.run(run())
    assert frames[-1]["type"] == "done"
    assert frames[-1].get("error") is not None      # 框架把异常记进最终 Msg.error


# ---------- SSE 端点 ----------


def test_chat_endpoint_sse_frames() -> None:
    archive = FakeArchive("sqlite:///:memory:")
    runner = fake_agent_runner([
        [{"type": "tool", "name": "query_deadlines"},
         {"type": "token", "text": "还剩 22 天"},
         {"type": "done", "reply": "还剩 22 天"}],
    ] + [[{"type": "done", "reply": "ok"}]] * 5)
    service = ChatService(archive, agent_runner=runner)
    client = TestClient(create_app(load_settings(), Usecases(chat=service)))

    resp = client.post("/api/chat", json={"message": "最近有什么截止"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = [json.loads(line.removeprefix("data: "))
              for line in resp.text.splitlines() if line.startswith("data: ")]
    assert frames[0]["type"] == "session"
    session_id = frames[0]["session_id"]
    types = [f["type"] for f in frames[1:]]
    assert types == ["tool", "token", "done"]
    assert frames[-1]["reply"] == "还剩 22 天"

    # 续聊带 session_id：runner 收到同一个会话号
    resp2 = client.post("/api/chat", json={"message": "再说", "session_id": session_id})
    assert resp2.status_code == 200
    assert runner.calls[-1]["session_id"] == session_id


def test_chat_endpoint_503_without_service() -> None:
    client = TestClient(create_app(load_settings(), Usecases()))
    resp = client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 503
    assert "DEEPSEEK_API_KEY" in resp.json()["detail"]


# ---------- 流式记账（M7+：聊天开 stream=True 后计价代理的生成器路径） ----------


class FakeStreamingModel:
    """流式假模型：__call__ 返回 async generator，usage 在最后一个 chunk
    （与 AgentScope 真模型 stream=True 的行为一致）。"""

    context_size = 100_000
    stream = True
    model = "fake-stream"
    formatter = SimpleNamespace(supported_input_media_types=["image/*"])

    def __init__(self, usage_on_tail: bool = True) -> None:
        self.usage_on_tail = usage_on_tail

    async def __call__(self, messages, tools=None, **kwargs):
        from agentscope.message import TextBlock
        from agentscope.model import ChatResponse, ChatUsage

        async def gen():
            for piece in ["你好", "，", "世界"]:
                yield ChatResponse(
                    content=[TextBlock(type="text", text=piece)],
                    is_last=False,
                )
            tail_usage = (ChatUsage(input_tokens=30, output_tokens=6, time=0.01)
                          if self.usage_on_tail else None)
            yield ChatResponse(content=[], is_last=True, usage=tail_usage)

        return gen()

    async def count_tokens(self, messages, tools=None) -> int:
        return 30

    async def generate_structured_output(self, *args, **kwargs):
        raise AssertionError("聊天不应触发结构化输出")


def _stream_profile_meter():
    profile = ModelProfile(name="t", base_url="https://x", api_key_env="K", model="t")
    return profile, CostMeter(profile=profile, task_type="chat")


def test_metered_model_streams_and_records_once() -> None:
    """流式返回：chunk 全部透传、usage 在尾 chunk、只记一次账。"""
    from contest_agent.application.harness.agent_factory import MeteredChatModel

    _, meter = _stream_profile_meter()
    proxy = MeteredChatModel(FakeStreamingModel(), meter)

    async def run():
        result = await proxy([{"role": "user", "content": "hi"}])
        pieces = []
        async for chunk in result:
            for b in getattr(chunk, "content", []) or []:
                if getattr(b, "type", "") == "text":
                    pieces.append(b.text)
        return pieces

    assert asyncio.run(run()) == ["你好", "，", "世界"]   # 增量原样透传
    assert meter.call_count == 1                          # 流结束记一次，不是每 chunk 一次


def test_metered_model_stream_without_usage_still_yields() -> None:
    """服务商没回 usage（异常情况）也不炸：chunk 照透传、账本零记录。"""
    from contest_agent.application.harness.agent_factory import MeteredChatModel

    _, meter = _stream_profile_meter()
    proxy = MeteredChatModel(FakeStreamingModel(usage_on_tail=False), meter)

    async def run():
        result = await proxy([{"role": "user", "content": "hi"}])
        count = 0
        async for _ in result:
            count += 1
        return count

    assert asyncio.run(run()) == 4                        # 3 个增量 + 1 个收尾
    assert meter.call_count == 0 and meter.spent_yuan == 0
