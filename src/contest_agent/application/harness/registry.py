"""工具注册表：agent 能用的"工具箱"，P4。

一个工具 = 名字 + 说明 + 参数规格（JSON Schema）+ 执行函数。
注册表干两件事：
1. 把工具清单翻译成 OpenAI function-calling 格式发给模型
   （模型只能看到名字/说明/参数规格，看不到函数本身）；
2. 模型点名要调某个工具时，负责真正执行它。

JSON Schema 是描述"这个函数接受什么参数"的行业标准格式，长这样：
    {"type": "object", "properties": {"文件名": {"type": "string"}}, "required": [...]}
模型照着它生成参数，我们照着它校验参数。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

ERROR_PREFIX = "工具执行出错"


@dataclass
class Tool:
    """一件工具的完整描述。func 返回字符串——返回给模型看的东西都得是文字。"""

    name: str
    description: str           # 给模型看的"使用说明书"，写清楚它才会用
    parameters: dict           # JSON Schema：参数长什么样
    func: Callable[..., str]   # 真正干活的函数


class ToolRegistry:
    """工具箱：注册、翻译成模型格式、按名执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """把一件工具放进工具箱（同名覆盖，方便测试）。"""
        self._tools[tool.name] = tool

    def openai_schemas(self) -> list[dict]:
        """把全部工具翻译成 OpenAI function-calling 要求的格式。

        模型只能看到这个清单（名字/说明/参数规格），
        所以 description 写得好不好，直接影响模型会不会用、用得对不对。
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def call(self, name: str, arguments: dict) -> str:
        """按名字执行工具，返回结果字符串。

        关键纪律：工具出错【不抛异常】，而是把错误信息当字符串返回——
        因为调用方是 agent 循环，错误文本会交回给模型看，
        模型看到"参数不对"会自己修正重试，这正是 ReAct 的运转方式。
        崩溃是人的体验，报错是模型的养料。
        """
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(self._tools) or "（一件都没有）"
            return f"{ERROR_PREFIX}：不存在名为 {name!r} 的工具。可用工具：{available}"

        try:
            return tool.func(**arguments)
        except TypeError as error:
            # 参数个数/名字对不上，多半是模型照 Schema 生成时跑偏了
            return f"{ERROR_PREFIX}：参数不匹配（{error}）。请对照工具说明修正参数后重试。"
        except Exception as error:  # noqa: BLE001 — 工具内部任何失败都转成文本
            return f"{ERROR_PREFIX}：{error}"
