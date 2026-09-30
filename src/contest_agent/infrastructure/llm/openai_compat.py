"""openai 兼容层的 LLM 客户端，实现 domain/ports.py 里的 LlmPort（P2）。

"OpenAI 兼容"是行业惯例：DeepSeek、通义千问等很多模型服务商都提供
和 OpenAI 一模一样的接口格式。所以只需要 openai 这一个 SDK，
换服务商 = 换 base_url + api_key + 模型名——正好对应 settings 里的"模型档案"。
"""

from __future__ import annotations

import json
import re
import time

from openai import OpenAI

from ...domain.entities import LlmReply, ToolCall
from ...settings import ModelProfile

MAX_RETRIES = 2        # 失败后最多重试几次（不含第一次）
RETRY_WAIT_SECONDS = 3  # 第一次重试前等多久（之后逐次翻倍）


def parse_json_loose(raw: str) -> dict:
    """把 LLM 返回的文本尽量解析成字典（宽容解析）。

    按理说开了 response_format=json_object 后返回一定是纯 JSON，
    但不同服务商实现不一，有的会在外面再包一层 ```json 代码围栏。
    所以分两步：先直接解析，失败就剥围栏再试，还不行就报错
    并附上原文开头——报错信息里带原文，排查时一眼能看出模型输出了什么。
    """
    text = raw.strip()

    # 第一步：当成纯 JSON 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 第二步：剥掉 Markdown 代码围栏（```json ... ```）再解析
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"LLM 返回的不是合法 JSON，原文开头：{raw[:120]!r}")


class OpenAiCompatLlm:
    """用 openai SDK 调用"任意兼容服务商"的 LLM。"""

    def __init__(self, profile: ModelProfile, client: OpenAI | None = None):
        self.profile = profile

        # 密钥必须在构造时检查清楚：等到调用才报错，排查起来绕得远
        api_key = profile.resolve_api_key()
        if not api_key:
            raise RuntimeError(
                f"模型档案 '{profile.name}' 缺少密钥：请设置环境变量 {profile.api_key_env}"
                f"（建议写进项目根目录的 .env 文件，该文件已被 gitignore，不会入库）"
            )

        # client 允许外部注入：单元测试时塞一个假客户端，就不用真调 API
        self._client = client or OpenAI(base_url=profile.base_url, api_key=api_key)

    def complete_structured(
        self, system: str, user: str, schema: dict | None = None
    ) -> dict:
        """单次结构化调用：发提示词，拿回解析好的 JSON 字典。

        两个关键参数：
        - response_format=json_object：让服务商开"JSON 模式"，
          大幅降低输出格式跑偏的概率（这是"结构化调用"的底气）；
        - temperature=0：识别/提取要的是准确和可复现，不是创意。
        schema 参数保留在签名里（将来可接严格校验），当前版本靠提示词约束格式。
        """
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self.profile.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0,
                )
                return parse_json_loose(resp.choices[0].message.content)
            except Exception as error:
                # SDK 的异常类很多（限流、超时、服务端错误），统一兜住重试；
                # 重试耗尽后在下面抛出带原因的异常
                last_error = error
                time.sleep(RETRY_WAIT_SECONDS * attempt)
        raise ConnectionError(f"LLM 调用失败（已重试 {MAX_RETRIES} 次）：{last_error}")

    def chat_with_tools(
        self, messages: list[dict], tools: list[dict], temperature: float = 0.5
    ) -> LlmReply:
        """带工具表的对话式调用，把 openai 格式的响应翻译成 LlmReply。

        翻译工作有两处讲究：
        1. 模型返回的 tool_calls 里，arguments 是 JSON "字符串"，
           这里负责解析成字典（解析失败不炸，包成 {"_raw": 原文} 交给上层，
           让循环把错误信息回传给模型自行纠正——这是 ReAct 的常规操作）；
        2. temperature 用 0.5 而不是 0：材料生成需要一点文采，
           但也不能太放飞（循环决策仍要稳定）。
        """
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self.profile.model,
                    messages=messages,
                    tools=tools or None,  # 空列表传 None，免得服务商挑理
                    temperature=temperature,
                )
                message = resp.choices[0].message

                tool_calls: list[ToolCall] = []
                for raw_call in message.tool_calls or []:
                    try:
                        arguments = json.loads(raw_call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        arguments = {"_raw": raw_call.function.arguments}
                    tool_calls.append(
                        ToolCall(
                            id=raw_call.id,
                            name=raw_call.function.name,
                            arguments=arguments,
                        )
                    )
                return LlmReply(content=message.content, tool_calls=tool_calls)
            except Exception as error:
                last_error = error
                time.sleep(RETRY_WAIT_SECONDS * attempt)
        raise ConnectionError(f"LLM 调用失败（已重试 {MAX_RETRIES} 次）：{last_error}")
