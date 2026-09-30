"""AgentScope 接驳层：把框架的循环与本项目的端口组装起来（v1.5 迁移后）。

分工边界：
- 循环本体（ReAct、消息协议、工具调度）由 AgentScope 的 Agent 驱动，
  我们不再手写——这正是 ADR-002 的决定；
- 工具函数包的仍然是 P1-P3 建好的端口能力（爬虫/仓储/输出目录），
  注册方式从"自研注册表"换成了 AgentScope 的 Toolkit；
- run_material_generation() 把框架的异步调用包成同步函数，供用例层使用。

两个迁移时踩到并解决的框架细节（给后来者省时间）：
1. AgentScope 2.0.8 的 Toolkit.add_tool / get_tool_schemas 都是异步方法；
2. 框架自带权限系统：未授权的工具会触发"等用户确认"而挂起。
   CLI 是无人值守场景，所以每个工具显式挂 PermissionDecision(ALLOW)，
   语义 = "用户已授权这些工具自动执行"。save_material 内部仍有
   路径/后缀校验作为硬约束，安全边界不依赖权限开关。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agentscope.agent import Agent, ReActConfig
from agentscope.credential import DeepSeekCredential, OpenAICredential
from agentscope.message import Msg, TextBlock
from agentscope.model import ChatModelBase, DeepSeekChatModel, OpenAIChatModel
from agentscope.permission import PermissionBehavior
from agentscope.permission._decision import PermissionDecision
from agentscope.tool import FunctionTool, Toolkit

from ...domain.entities import Notice
from ...domain.ports import CompetitionRepositoryPort, NoticeSourcePort, SearchPort
from ...settings import ModelProfile

# 发给模型的正文上限：通知全文可能很长，模型不需要逐字看完全文
MAX_NOTICE_CHARS = 4000

# CLI 无人值守：显式授权工具自动执行（每个工具的硬约束仍由函数自身把守）
ALLOWED = PermissionDecision(
    behavior=PermissionBehavior.ALLOW,
    message="CLI 无人值守模式，该工具已获用户授权自动执行",
)


@dataclass
class AgentOutcome:
    """一次 agent 运行的结果（用例层只关心这两样）。"""

    final_text: str
    error: str | None  # None = 正常结束


@dataclass
class MaterialTools:
    """工具箱 + 共享轨迹 + 原函数（测试可以直接调函数，不必过框架）。"""

    toolkit: Toolkit
    trace: list[str] = field(default_factory=list)
    functions: dict[str, Callable[..., str]] = field(default_factory=dict)


def build_chat_model(profile: ModelProfile) -> ChatModelBase:
    """按模型档案创建 AgentScope 的聊天模型客户端。

    密钥缺失在这里立刻报错，错误信息直接告诉用户该设置哪个环境变量。
    """
    api_key = profile.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            f"模型档案 '{profile.name}' 缺少密钥：请设置环境变量 {profile.api_key_env}"
            f"（建议写进项目根目录的 .env 文件，该文件已被 gitignore，不会入库）"
        )

    if "deepseek" in profile.base_url:
        return DeepSeekChatModel(
            credential=DeepSeekCredential(api_key=api_key, base_url=profile.base_url),
            model=profile.model,
            stream=False,
            max_retries=2,
        )
    # 其他 OpenAI 兼容服务商（如通义千问）走通用 OpenAI 协议
    return OpenAIChatModel(
        credential=OpenAICredential(api_key=api_key, base_url=profile.base_url),
        model=profile.model,
        stream=False,
        max_retries=2,
    )


def _make_save_material(output_dir: Path, trace: list[str]) -> Callable[..., str]:
    """制造"保存材料"工具函数（材料和备考路径两个任务共用）。

    单独抽出来是因为它带着安全硬约束（防路径穿越、只许 .md），
    两处使用必须保证规则完全一致——抽成一处，规则就不会漂移。
    """
    def save_material(filename: str, content: str) -> str:
        """把写好的材料保存为 Markdown 文件。filename 只写文件名（如 ppt-outline.md），content 是完整全文。"""
        trace.append(f"save_material({filename}, {len(content)} 字)")
        # 硬约束一：只允许纯文件名，不许带路径（防 ../ 目录穿越）
        if Path(filename).name != filename:
            return f"保存失败：文件名 {filename!r} 不能包含路径，只写文件名如 'ppt-outline.md'。"
        # 硬约束二：只允许 Markdown 文件，材料格式保持统一
        if not filename.endswith(".md"):
            return "保存失败：文件必须以 .md 结尾。"

        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / filename
        target.write_text(content, encoding="utf-8")
        return f"已保存：{target}（{len(content)} 字）"

    return save_material


async def build_material_tools(
    source: NoticeSourcePort,
    competition_repository: CompetitionRepositoryPort,
    output_dir: Path,
) -> MaterialTools:
    """把三件工具注册进 AgentScope 的 Toolkit（异步：框架要求）。

    工具的说明书由 AgentScope 自动生成——从函数的 docstring 和
    类型标注提取，所以注释写得越清楚，模型用得越准。
    trace 列表由各闭包写入，跑完后供 CLI 播报"agent 干了什么"。
    """
    tools = MaterialTools(toolkit=Toolkit())

    def list_competitions() -> str:
        """列出数据库里全部比赛卡片，含名称、类型、截止日期和通知链接。"""
        tools.trace.append("list_competitions()")
        cards = competition_repository.list_all()
        if not cards:
            return "库里还没有比赛卡片。请提示用户先运行 sai identify 识别比赛。"
        lines = []
        for index, card in enumerate(cards, start=1):
            deadline = card.deadline.strftime("%Y-%m-%d") if card.deadline else "未写"
            lines.append(
                f"{index}. {card.name}（{card.type}，截止 {deadline}）"
                f" 通知：{card.notice_url}"
            )
        return "\n".join(lines)

    def get_notice_content(notice_url: str) -> str:
        """读取一条比赛通知的正文原文。notice_url 填通知详情页的完整网址。"""
        tools.trace.append(f"get_notice_content({notice_url})")
        notice = source.fetch_detail(Notice(source_url=notice_url, title=""))
        if not notice.content:
            return "这条通知没有抓到正文（可能是图片/外链形式）。"
        return notice.content[:MAX_NOTICE_CHARS]

    save_material = _make_save_material(output_dir, tools.trace)

    functions = {
        "list_competitions": list_competitions,
        "get_notice_content": get_notice_content,
        "save_material": save_material,
    }
    for func in functions.values():
        # permission=ALLOWED：无人值守授权自动执行（见模块 docstring 第 2 点）
        await tools.toolkit.add_tool(FunctionTool(func=func, permission=ALLOWED))
    tools.functions = functions
    return tools


async def build_study_tools(
    search: SearchPort,
    competition_repository: CompetitionRepositoryPort,
    output_dir: Path,
) -> MaterialTools:
    """备考路径任务的工具箱：联网搜索 + 读网页 + 落盘 + 查卡片（P5）。"""

    tools = MaterialTools(toolkit=Toolkit())

    def search_web(query: str, max_results: int = 5) -> str:
        """联网搜索资料。query 填搜索词（如 '蓝桥杯 真题 备考'），返回带网址的结果列表。"""
        tools.trace.append(f"search_web({query!r})")
        results = search.search(query, top_k=max_results)
        if not results:
            return "搜索暂时没有返回结果（可能网络波动），请换个搜索词重试。"
        lines = []
        for index, item in enumerate(results, start=1):
            lines.append(f"{index}. {item['title']}\n   网址：{item['url']}\n   摘要：{item['snippet']}")
        return "\n".join(lines)

    def read_page(url: str) -> str:
        """读取一个网页的正文内容，用于确认链接真实可用、内容相关后再引用。url 填完整网址。"""
        tools.trace.append(f"read_page({url})")
        return search.read_page(url)

    save_material = _make_save_material(output_dir, tools.trace)

    def list_competitions() -> str:
        """列出数据库里全部比赛卡片，含名称、类型、截止日期和通知链接。"""
        tools.trace.append("list_competitions()")
        cards = competition_repository.list_all()
        if not cards:
            return "库里还没有比赛卡片。请提示用户先运行 sai identify 识别比赛。"
        lines = []
        for index, card in enumerate(cards, start=1):
            deadline = card.deadline.strftime("%Y-%m-%d") if card.deadline else "未写"
            lines.append(
                f"{index}. {card.name}（{card.type}，截止 {deadline}）"
                f" 通知：{card.notice_url}"
            )
        return "\n".join(lines)

    functions = {
        "search_web": search_web,
        "read_page": read_page,
        "save_material": save_material,
        "list_competitions": list_competitions,
    }
    for func in functions.values():
        await tools.toolkit.add_tool(FunctionTool(func=func, permission=ALLOWED))
    tools.functions = functions
    return tools


async def _run_material_agent_async(
    profile: ModelProfile,
    system_prompt: str,
    user_request: str,
    tools: MaterialTools,
    max_iters: int,
) -> AgentOutcome:
    """组装 Agent 并跑完一次材料生成任务（异步版）。"""
    agent = Agent(
        name="material_agent",
        system_prompt=system_prompt,
        model=build_chat_model(profile),
        toolkit=tools.toolkit,
        react_config=ReActConfig(max_iters=max_iters),
    )
    reply = await agent.reply(
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text=user_request)],
        )
    )
    # 回复的 content 是块列表，把文本块拼成完整收尾陈述
    text = "\n".join(
        block.text for block in reply.content if getattr(block, "type", "") == "text"
    )
    return AgentOutcome(final_text=text, error=None if reply.error is None else str(reply.error))


def run_material_generation(
    profile: ModelProfile,
    system_prompt: str,
    user_request: str,
    tools_builder: Callable[[], Awaitable[MaterialTools]],
    max_iters: int = 8,
) -> tuple[AgentOutcome, MaterialTools]:
    """同步门面：建工具箱 -> 组 Agent -> 跑循环，返回结果和工具轨迹。

    tools_builder：零参数的异步函数，返回装好工具的 MaterialTools
    （异步是框架要求——add_tool 是异步方法）。材料生成和备考路径
    两个任务各自传入自己的工具箱构建器。
    用 asyncio.run 包装异步调用，让用例层和 CLI 保持同步代码风格。
    注意：未来 FastAPI 异步环境调用时要换成 await 版本（P6 处理）。
    """

    async def pipeline() -> tuple[AgentOutcome, MaterialTools]:
        tools = await tools_builder()
        outcome = await _run_material_agent_async(
            profile, system_prompt, user_request, tools, max_iters
        )
        return outcome, tools

    return asyncio.run(pipeline())
