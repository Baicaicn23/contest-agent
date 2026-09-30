"""流式自由对话的 OpenAI 兼容实现（M4），实现 domain 的 ChatStreamPort。

和 OpenAiCompatLlm（结构化调用）是兄弟：同一个 openai SDK、同一套
模型档案，但开 stream=True 逐段收回复——前端才能逐字打出来。
用 stream_options 让服务商在最后一个分块里回报 usage，照常进台账。
"""

from __future__ import annotations

from collections.abc import Iterator

from openai import OpenAI

from ...settings import ModelProfile


class OpenAiStreamChat:
    """流式对话客户端，实现 ChatStreamPort。"""

    def __init__(self, profile: ModelProfile, client: OpenAI | None = None, meter=None):
        self.profile = profile
        self._client = client or OpenAI(
            base_url=profile.base_url, api_key=profile.resolve_api_key()
        )
        self.meter = meter

    def with_meter(self, meter) -> "OpenAiStreamChat":
        """返回绑定了新计价器的浅拷贝（共享底层 HTTP 客户端，构造很便宜）。

        每个聊天会话一个计价器：该会话的每轮花费都记到同一个 session_id 名下。
        """
        return OpenAiStreamChat(self.profile, client=self._client, meter=meter)

    def stream(self, system: str, messages: list[dict]) -> Iterator[str]:
        """逐段产出回复文本；结束时把 usage 记进台账（有计价器的话）。"""
        if self.meter is not None:
            self.meter.precheck()  # 预算花满：这一轮根本不发

        payload = [{"role": "system", "content": system}, *messages]
        stream = self._client.chat.completions.create(
            model=self.profile.model,
            messages=payload,
            stream=True,
            # 让服务商在最后一个分块带回本次调用的 token 用量（没有它流式就记不了账）
            stream_options={"include_usage": True},
            temperature=0.7,
        )
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None and self.meter is not None:
                # usage 在最后一个分块：prompt/completion 与非流式接口同名字段
                self.meter.record(
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                )
            choices = getattr(chunk, "choices", None)
            if choices:
                delta = getattr(choices[0], "delta", None)
                text = getattr(delta, "content", None)
                if text:
                    yield text
