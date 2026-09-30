"""M4 后端（二）验收测试：自由对话 ChatService 与 /api/chat SSE 端点。

全程用假流式客户端（逐段吐固定文本），不碰网络不花钱。
"""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from contest_agent.application.cost import BudgetExceededError, CostMeter
from contest_agent.application.usecases.chat_service import ChatService
from contest_agent.infrastructure.llm.openai_stream import OpenAiStreamChat
from contest_agent.infrastructure.persistence.repository import (
    SqliteSessionRepository,
    SqliteUsageRepository,
)
from contest_agent.presentation.server import Usecases, create_app
from contest_agent.settings import ModelProfile, load_settings


# ---------- 假对象 ----------


class FakeStreamChat:
    """假流式客户端：分三段吐"你好呀"；记录收到的 system 和 messages。"""

    def __init__(self, boom: bool = False) -> None:
        self.boom = boom
        self.system = ""
        self.messages: list[dict] = []

    def with_meter(self, meter) -> "FakeStreamChat":
        # 与真实现不同：这里返回自身并记住计价器，方便测试断言
        # （真 OpenAiStreamChat 返回共享底层客户端的浅拷贝）
        self.meter = meter
        return self

    def stream(self, system: str, messages: list[dict]):
        if self.boom:
            raise BudgetExceededError("预算熔断：已达上限")
        self.system = system
        self.messages = list(messages)
        for piece in ["你", "好", "呀"]:
            yield piece


class FakeMeterFactory:
    """假计价器工厂：记录每次造计价器用的会话号。"""

    def __init__(self) -> None:
        self.session_ids: list[int] = []

    def __call__(self, session_id: int) -> CostMeter:
        self.session_ids.append(session_id)
        profile = ModelProfile(name="t", base_url="https://x",
                               api_key_env="K", model="t-chat")
        return CostMeter(profile=profile, task_type="chat", budget_yuan=None)


# ---------- ChatService ----------


def test_chat_service_round_writes_events_and_streams() -> None:
    archive = SqliteSessionRepository("sqlite:///:memory:")
    service = ChatService(FakeStreamChat(), archive, meter_factory=FakeMeterFactory(),
                          model_name="t-chat")

    session_id = service.open_session()
    chunks = list(service.stream_reply(session_id, "你好"))

    assert [c["type"] for c in chunks] == ["token", "token", "token", "done"]
    assert chunks[-1]["reply"] == "你好呀"

    # 轨迹：user_input 和 result 都进了会话存档
    _, events = archive.get_session(session_id)
    kinds = [e.kind for e in events]
    assert kinds == ["user_input", "result"]
    assert events[1].payload["final_text"] == "你好呀"


def test_chat_service_multi_round_history_window() -> None:
    """多轮对话：上下文带最近几轮（超出窗口的旧轮被裁掉）。"""
    archive = SqliteSessionRepository("sqlite:///:memory:")
    stream = FakeStreamChat()
    service = ChatService(stream, archive, meter_factory=FakeMeterFactory())

    session_id = service.open_session()
    for i in range(8):  # 聊 8 轮，窗口只有 6 轮
        list(service.stream_reply(session_id, f"消息{i}"))

    list(service.stream_reply(session_id, "第 9 问"))
    # 最后一轮发给模型的 messages：窗口 12 条（最近 6 轮，从第 16 条往前切，
    # 开头正好落在第 2 轮的助手回复上）+ 当前 1 条 = 13 条
    assert len(stream.messages) == 13
    assert stream.messages[0]["content"] == "你好呀"    # a2：窗口切在轮中间的助手消息
    assert "消息3" in [m["content"] for m in stream.messages]
    assert "消息0" not in [m["content"] for m in stream.messages]  # 最老的被裁掉
    assert stream.messages[-1]["content"] == "第 9 问"
    # 系统提示词单独走 stream.system，openai messages 里只有 user/assistant
    assert all(m["role"] in ("user", "assistant") for m in stream.messages)
    assert "比赛情报助手" in stream.system


def test_chat_service_budget_break_yields_error_event() -> None:
    archive = SqliteSessionRepository("sqlite:///:memory:")
    service = ChatService(FakeStreamChat(boom=True), archive,
                          meter_factory=FakeMeterFactory())

    session_id = service.open_session()
    chunks = list(service.stream_reply(session_id, "你好"))

    assert chunks[-1]["type"] == "error"
    assert "预算熔断" in chunks[-1]["error"]
    # 错误也留档（回放时看得到为什么没回话）
    _, events = archive.get_session(session_id)
    assert events[-1].kind == "error"


def test_chat_service_system_prompt_injects_live_data() -> None:
    usage = SqliteUsageRepository("sqlite:///:memory:")
    from contest_agent.domain.entities import UsageEntry

    usage.record(UsageEntry("chat", "deepseek", "deepseek-chat", 100, 10, 0.00028,
                            created_at=datetime.now()))
    archive = SqliteSessionRepository("sqlite:///:memory:")
    service = ChatService(FakeStreamChat(), archive, usage_repository=usage,
                          meter_factory=FakeMeterFactory(), model_name="t-chat")

    prompt = service.system_prompt()
    assert "0.0003" in prompt or "0.00028" in prompt   # 今日花费注入
    assert "t-chat" in prompt


# ---------- OpenAiStreamChat（假 openai 客户端测流式解析与记账） ----------


class _Chunk:
    def __init__(self, content=None, usage=None):
        self.choices = [] if content is None and usage is not None else [
            type("C", (), {"delta": type("D", (), {"content": content})()})()
        ]
        self.usage = usage


class _FakeStreamClient:
    """假 openai 客户端：create(stream=True) 返回预设分块，并记录调用参数。"""

    def __init__(self, chunks) -> None:
        self._chunks = chunks
        self.kwargs = {}
        self.chat = type("Chat", (), {"completions": type(
            "Completions", (), {"create": self._create})()})()

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return iter(self._chunks)


def test_openai_stream_chat_yields_and_records_usage() -> None:
    from types import SimpleNamespace

    usage_chunk = SimpleNamespace(choices=[], usage=SimpleNamespace(
        prompt_tokens=100, completion_tokens=20))
    client = _FakeStreamClient([
        _Chunk(content="你"), _Chunk(content="好"), usage_chunk,
    ])
    profile = ModelProfile(name="t", base_url="https://x", api_key_env="K",
                           model="t-chat")
    meter = CostMeter(profile=profile, task_type="chat")
    chat = OpenAiStreamChat(profile, client=client, meter=meter)

    deltas = list(chat.stream("系统提示", [{"role": "user", "content": "hi"}]))

    assert deltas == ["你", "好"]
    assert meter.call_count == 1
    assert meter.spent_yuan >= 0
    assert client.kwargs["stream"] is True
    assert client.kwargs["stream_options"] == {"include_usage": True}
    assert client.kwargs["messages"][0] == {"role": "system", "content": "系统提示"}


# ---------- SSE 端点 ----------


def test_chat_endpoint_sse_frames() -> None:
    archive = SqliteSessionRepository("sqlite:///:memory:")
    service = ChatService(FakeStreamChat(), archive, meter_factory=FakeMeterFactory())
    client = TestClient(create_app(load_settings(), Usecases(chat=service)))

    resp = client.post("/api/chat", json={"message": "你好"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = [json.loads(line.removeprefix("data: "))
              for line in resp.text.splitlines() if line.startswith("data: ")]
    assert frames[0]["type"] == "session"
    session_id = frames[0]["session_id"]
    types = [f["type"] for f in frames[1:]]
    assert types == ["token", "token", "token", "done"]
    assert frames[-1]["reply"] == "你好呀"

    # 第二轮带 session_id：同一会话继续（事件追加而非新开）
    resp2 = client.post("/api/chat", json={"message": "再来", "session_id": session_id})
    frames2 = [json.loads(l.removeprefix("data: "))
               for l in resp2.text.splitlines() if l.startswith("data: ")]
    assert frames2[0]["session_id"] == session_id

    # 新会话按钮 = close 旧会话
    resp3 = client.post("/api/chat/close", json={"session_id": session_id})
    assert resp3.status_code == 200


def test_chat_endpoint_503_without_service() -> None:
    client = TestClient(create_app(load_settings(), Usecases()))
    resp = client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 503
    assert "DEEPSEEK_API_KEY" in resp.json()["detail"]
