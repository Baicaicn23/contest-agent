"""ReAct 循环引擎：本项目手写 harness 的心脏（P4）。

ReAct = Reasoning + Acting：模型思考下一步 -> 调工具 -> 看结果 -> 再思考……
直到它认为任务完成，用一段文字收尾。

整个引擎只有一个值得读懂的方法：run()。消息列表 messages 是循环的
"工作记忆"，按 OpenAI 的对话协议滚动追加：

    [system] 系统提示词（你是谁、守什么规矩）
    [user]   用户请求（为某比赛生成材料）
    [assistant] 模型说：我要调工具 X（带 tool_calls）
    [tool]   工具结果（凭 tool_call_id 对号入座）
    [assistant] 模型看完结果：我再调工具 Y / 任务完成，总结如下
    ...

为什么必须有 max_steps？——模型有可能陷入"调工具 -> 不满意 -> 再调"的
死循环，烧钱不产出。给循环装个里程表，到站强制停车并如实报告失败。
真实产品（Claude Code 等）都有同样的机制。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ...domain.entities import LlmReply
from ...domain.ports import LlmPort
from .registry import ToolRegistry


@dataclass
class AgentStep:
    """一轮循环的记录（给 CLI 展示轨迹、给测试做断言）。"""

    step: int
    assistant_content: str | None          # 模型这一轮说了什么（可能为空）
    tool_calls: list[dict] = field(default_factory=list)
    # 每个元素：{"name", "arguments", "result"}（result 截断存预览）


@dataclass
class AgentResult:
    """一次完整运行的结果。"""

    final_text: str        # 模型的收尾陈述
    steps: list[AgentStep]
    success: bool          # True=模型自然收尾；False=步数耗尽被强制停


class AgentRunner:
    """把 LLM、工具箱、系统提示词组装成一个会干活的循环。"""

    def __init__(
        self,
        llm: LlmPort,
        registry: ToolRegistry,
        system_prompt: str,
        max_steps: int = 8,
    ):
        self.llm = llm
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_steps = max_steps

    def run(self, user_request: str) -> AgentResult:
        """跑一次完整循环，直到模型收尾或步数耗尽。"""
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_request},
        ]
        steps: list[AgentStep] = []

        for step_number in range(1, self.max_steps + 1):
            reply: LlmReply = self.llm.chat_with_tools(
                messages, self.registry.openai_schemas()
            )

            # 出口：模型没有发起任何工具调用 = 它认为活干完了
            if not reply.tool_calls:
                steps.append(
                    AgentStep(step=step_number, assistant_content=reply.content)
                )
                return AgentResult(
                    final_text=reply.content or "（模型没有给出收尾陈述）",
                    steps=steps,
                    success=True,
                )

            # 模型要调工具：先把它的"动手决定"按协议追加进对话历史，
            # （assistant 消息必须原样带回 tool_calls 和 id，这是协议要求）
            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(
                                    call.arguments, ensure_ascii=False
                                ),
                            },
                        }
                        for call in reply.tool_calls
                    ],
                }
            )

            step_record = AgentStep(
                step=step_number, assistant_content=reply.content
            )

            # 逐个执行工具，结果以 role=tool 追加回历史，供模型下一轮阅读
            for call in reply.tool_calls:
                result = self.registry.call(call.name, call.arguments)
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )
                step_record.tool_calls.append(
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "result": result[:200],  # 只存预览，记录别撑爆
                    }
                )

            steps.append(step_record)

        # 走到这说明 max_steps 用尽模型还没收尾：强制停车，如实报告失败
        return AgentResult(
            final_text=(
                f"任务未完成：已达到最大步数（{self.max_steps}），"
                f"模型仍在调用工具。可尝试提高 --max-steps 或简化任务。"
            ),
            steps=steps,
            success=False,
        )
