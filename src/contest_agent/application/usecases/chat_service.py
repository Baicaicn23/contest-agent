"""chat_service 用例：自由对话的编排层（M4 前端聊天区的后端）。

职责三件事：
1. **人设**：系统提示词 = "比赛情报助手"角色 + 实时注入项目数据
   （库里有几张卡片、今天花了多少钱、当前用的什么模型）——
   所以它回答"我今天花了多少钱"这类问题不用查库，张口就来；
2. **记忆**：从会话存档里取同会话最近几轮对话当上下文（多轮聊天
   不是每次失忆；M4 用"拼进 messages"的朴素办法，上下文压缩留给后续）；
3. **轨迹**：每轮把 user_input / result 写进会话存档——聊天记录
   在 sai replay / 前端会话列表里可见，和其他任务一视同仁。

流式本身不做：ChatStreamPort（基础设施的 OpenAI 流式客户端）负责
逐段产出，本用例负责在它前后编排（存事件、拼上下文、兜错误）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime

from ...domain.ports import (
    ChatStreamPort,
    CompetitionRepositoryPort,
    SessionArchivePort,
    UsageRepositoryPort,
)
from ..cost import BudgetExceededError

# 带进上下文的最大轮数（一轮 = 一条用户消息 + 一条助手回复，即 2 条消息）
CHAT_HISTORY_ROUNDS = 6


class ChatService:
    """自由对话的编排器。由装配根构建；HTTP 层每请求调用 stream_reply。"""

    def __init__(
        self,
        stream_chat: ChatStreamPort,
        archive: SessionArchivePort,
        competition_repository: CompetitionRepositoryPort | None = None,
        usage_repository: UsageRepositoryPort | None = None,
        meter_factory: Callable[[int], object] | None = None,
        model_name: str = "",
    ):
        self.stream_chat = stream_chat
        self.archive = archive
        self.competition_repository = competition_repository
        self.usage_repository = usage_repository
        # meter_factory(session_id) -> CostMeter：每个聊天会话一个计价器，
        # 会话内所有轮次的花费记到同一个 session_id 名下
        self.meter_factory = meter_factory
        self.model_name = model_name

    # ---------- 会话 ----------

    def open_session(self, note: str = "web") -> int:
        """开一个聊天会话，返回编号。"""
        return self.archive.create_session("chat", note)

    def close_session(self, session_id: int) -> None:
        """正常收尾一个聊天会话（前端点"新会话"时调用）。"""
        try:
            self.archive.finish_session(session_id, "completed")
        except Exception:
            pass  # 存档故障不影响对话（M2 的老规矩）

    # ---------- 人设与上下文 ----------

    def system_prompt(self) -> str:
        """系统提示词：助手角色 + 实时注入的项目数据。"""
        cards = 0
        if self.competition_repository is not None:
            try:
                cards = len(self.competition_repository.list_all())
            except Exception:
                cards = 0
        today_cost = None
        if self.usage_repository is not None:
            try:
                today = self.usage_repository.list_entries(
                    on_date=datetime.now().date()
                )
                today_cost = sum(
                    (e.cost_yuan or 0.0) for e in today
                )
            except Exception:
                today_cost = None

        cost_line = (
            f"今天的 LLM 花费约 {today_cost:.4f} 元。"
            if today_cost is not None else ""
        )
        return (
            "你是「比赛情报助手」，运行在一个自动盯学院官网、识别比赛、"
            "生成参赛材料的项目里。\n"
            f"当前使用的模型是 {self.model_name or '未知名'}。"
            f"库里现有 {cards} 张比赛卡片。{cost_line}\n"
            "回答要简洁、说人话；涉及比赛数据的以这里注入的实时数据为准；"
            "被问到怎么用本项目时，提示可用命令 sai scan/identify/generate/"
            "study-path/watch/cost/eval。"
        )

    def history(self, session_id: int) -> list[dict]:
        """取同会话最近 CHAT_HISTORY_ROUNDS 轮（= 轮数×2 条消息），拼成 openai 格式。"""
        try:
            _, events = self.archive.get_session(session_id)
        except Exception:
            return []
        turns: list[dict] = []
        for event in events:
            payload = event.payload or {}
            if event.kind == "user_input" and payload.get("text"):
                turns.append({"role": "user", "content": payload["text"]})
            elif event.kind == "result" and payload.get("final_text"):
                turns.append({"role": "assistant", "content": payload["final_text"]})
        return turns[-(CHAT_HISTORY_ROUNDS * 2):]

    # ---------- 一轮对话 ----------

    def stream_reply(self, session_id: int, user_text: str) -> Iterator[dict]:
        """跑一轮对话，逐个产出事件字典（HTTP 层转成 SSE 帧）：

        {"type": "token", "text": "…"}  文本增量（若干个）
        {"type": "done", "reply": "…"}  完成，带完整回复
        {"type": "error", "error": "…"} 出错（预算熔断等）
        """
        self._log(session_id, "user_input", {"text": user_text})

        # 上下文 = 当前这条之前的最近几轮 + 当前这条
        messages = self.history(session_id) + [{"role": "user", "content": user_text}]

        stream_chat = self.stream_chat
        if self.meter_factory is not None:
            try:
                stream_chat = stream_chat.with_meter(self.meter_factory(session_id))
            except BudgetExceededError as error:
                # 计价器构造时就会做 precheck：这个会话的预算已经花满
                self._log(session_id, "error", {"error": str(error)})
                yield {"type": "error", "error": str(error)}
                return

        collected: list[str] = []
        try:
            for delta in stream_chat.stream(self.system_prompt(), messages):
                collected.append(delta)
                yield {"type": "token", "text": delta}
        except BudgetExceededError as error:
            self._log(session_id, "error", {"error": str(error)})
            yield {"type": "error", "error": str(error)}
            return

        reply = "".join(collected)
        self._log(session_id, "result", {"final_text": reply})
        yield {"type": "done", "reply": reply}

    def _log(self, session_id: int, kind: str, payload: dict) -> None:
        """写会话事件；存档故障不影响对话（沿 TaskRecorder 的老规矩）。"""
        try:
            self.archive.append_event(session_id, kind, payload)
        except Exception:
            pass
