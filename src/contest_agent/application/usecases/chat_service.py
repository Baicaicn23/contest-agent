"""chat_service 用例：聊天区背后的"会行动的 agent"（M4 差异化改造）。

改造前：纯 LLM 文本调用——模型只能看注入的静态数字，被用户抓包
"为什么它没法直接去操作"。改造后：对话背后跑的是真正的 AgentScope
ReAct 循环（挂聊天工具箱：查卡片/读通知/搜索/查截止/扫官网/识别），
用户在前台就能让 agent 干活，和用 Claude 一样。

本用例只负责"编排层"的四件事：
1. **人设**：系统提示词 = 助手角色 + 实时注入项目数据（卡片数/今日花费/模型名）；
2. **多轮**：从会话存档取最近 6 轮拼成上下文；
3. **轨迹**：user_input / tool / result / error 全部写进会话存档（回放可见）；
4. **流式**：把 harness 胶水（run_chat_agent_stream）的帧原样交给 HTTP 层。

真正的 agent 循环在 harness/agent_factory.run_chat_agent_stream——
本类通过注入的 agent_runner 调用它（测试时塞假 runner）。
"""

from __future__ import annotations

from collections.abc import Callable

from ...domain.ports import (
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
        archive: SessionArchivePort,
        competition_repository: CompetitionRepositoryPort | None = None,
        usage_repository: UsageRepositoryPort | None = None,
        agent_runner: Callable | None = None,
        model_name: str = "",
    ):
        self.archive = archive
        self.competition_repository = competition_repository
        self.usage_repository = usage_repository
        # agent_runner(session_id, system_prompt, history, user_text) ->
        #   异步函数，await 后返回聊天帧异步生成器。由装配根注入：
        #   内部按会话号现造计价器与全套工具（构建工具箱本身是异步的），
        #   模型循环在 harness 胶水里。
        self.agent_runner = agent_runner
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
            pass

    # ---------- 人设与上下文 ----------

    def system_prompt(self) -> str:
        """系统提示词：助手角色 + 实时注入的项目数据 + 工具使用引导。"""
        cards = 0
        if self.competition_repository is not None:
            try:
                cards = len(self.competition_repository.list_all())
            except Exception:
                cards = 0
        today_cost = None
        if self.usage_repository is not None:
            try:
                from datetime import datetime

                today = self.usage_repository.list_entries(
                    on_date=datetime.now().date()
                )
                today_cost = sum((e.cost_yuan or 0.0) for e in today)
            except Exception:
                today_cost = None

        cost_line = (
            f"今天的 LLM 花费约 {today_cost:.4f} 元。" if today_cost is not None else ""
        )
        return (
            "你是「比赛情报助手」，运行在一个自动盯学院官网、识别比赛、生成参赛"
            "材料的项目里。你手里有工具：查比赛卡片、读通知原文、联网搜索、"
            "查截止日期、扫描官网最新通知、识别最新通知是否比赛。\n"
            f"当前模型 {self.model_name or '未知名'}。库里现有 {cards} 张比赛卡片。{cost_line}\n"
            "工作方式：用户让你查什么、准备什么，直接调工具去做，拿到结果再回答，"
            "不要让用户自己去敲命令；回答简洁、说人话；涉及比赛数据以工具结果为准。"
        )

    def history(self, session_id: int) -> list[dict]:
        """取同会话最近 CHAT_HISTORY_ROUNDS 轮（= 轮数×2 条消息），拼成消息列表。"""
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

    async def stream_reply(self, session_id: int, user_text: str):
        """跑一轮对话，逐个产出事件字典（HTTP 层转成 SSE 帧）：

        {"type": "token", "text": …}        文本增量
        {"type": "tool", "name": …}         一次工具调用
        {"type": "done", "reply": …}        完成，带完整回复
        {"type": "error", "error": …}       出错（预算熔断等）
        """
        self._log(session_id, "user_input", {"text": user_text})
        # 状态对齐（M8）：续聊的旧会话可能是 completed，本轮开始置回 running；
        # 侧栏树的转圈以这个字段为准。置失败（会话不存在）不影响对话。
        try:
            self.archive.set_status(session_id, "running")
        except Exception:
            pass

        history = self.history(session_id)
        collected: list[str] = []
        try:
            stream = await self.agent_runner(
                session_id, self.system_prompt(), history, user_text
            )
            async for chunk in stream:
                if chunk.get("type") == "tool":
                    # 工具调用留档：回放时看得到 agent 干了什么
                    self._log(session_id, "tool_call",
                              {"tool": chunk.get("name", ""), "result": ""})
                    yield chunk
                elif chunk.get("type") == "done":
                    reply = chunk.get("reply", "")
                    collected.append(reply)
                    if chunk.get("error"):
                        self._log(session_id, "error", {"error": chunk["error"]})
                        self._set_finished(session_id, "failed")
                        yield {"type": "error", "error": chunk["error"]}
                    else:
                        self._log(session_id, "result", {"final_text": reply})
                        self._set_finished(session_id, "completed")
                        yield {"type": "done", "reply": reply}
                else:
                    yield chunk
        except BudgetExceededError as error:
            self._log(session_id, "error", {"error": str(error)})
            self._set_finished(session_id, "failed")
            yield {"type": "error", "error": str(error)}
        except Exception as error:
            self._log(session_id, "error", {"error": str(error)})
            self._set_finished(session_id, "failed")
            yield {"type": "error", "error": str(error)}

    def _set_finished(self, session_id: int, status: str) -> None:
        """一轮结束（completed/failed）。会话还能续聊，下一轮开始会置回 running。"""
        try:
            self.archive.set_status(session_id, status)
        except Exception:
            pass

    def _log(self, session_id: int, kind: str, payload: dict) -> None:
        """写会话事件；存档故障不影响对话（TaskRecorder 的老规矩）。"""
        try:
            self.archive.append_event(session_id, kind, payload)
        except Exception:
            pass
