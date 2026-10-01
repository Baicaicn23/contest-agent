"""AgentScope 接驳层：把框架的循环与本项目的端口组装起来（v1.5 迁移后）。

分工边界：
- 循环本体（ReAct、消息协议、工具调度）由 AgentScope 的 Agent 驱动，
  我们不再手写——这正是 ADR-002 的决定；
- 工具函数包的仍然是 P1-P3 建好的端口能力（爬虫/仓储/输出目录），
  注册方式从"自研注册表"换成了 AgentScope 的 Toolkit；
- run_material_generation() 把框架的异步调用包成同步函数，供用例层使用。

M1 新增两件横切能力（都通过"注入"挂进来，工具函数零改动）：
- CostMeter 计价器：用 MeteredChatModel 代理包住框架的模型客户端，
  每轮模型调用都过一遍"预算熔断 -> 调用 -> 记账"（代理模式，
  类比 Java 的动态代理 AOP）；
- 上下文压缩：把阈值配置（ContextConfig）透传给框架 Agent，
  上下文超阈值时框架自动把旧对话压成结构化摘要（见 ADR-003）。

框架细节备忘（给后来者省时间）：
1. AgentScope 2.0.8 的 Toolkit.add_tool / get_tool_schemas 都是异步方法；
2. 框架自带权限系统：未授权的工具会触发"等用户确认"而挂起。
   CLI 是无人值守场景，所以每个工具显式挂 PermissionDecision(ALLOW)，
   语义 = "用户已授权这些工具自动执行"。save_material 内部仍有
   路径/后缀校验作为硬约束，安全边界不依赖权限开关。
3. Agent 对模型客户端是"鸭子类型"用法：只要求会 __call__ /
   count_tokens / generate_structured_output / context_size，
   所以代理不需要继承 ChatModelBase，实现同名方法即可冒充。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Callable

from agentscope.agent import Agent, ContextConfig, ReActConfig
from agentscope.credential import DeepSeekCredential, OpenAICredential
from agentscope.message import Msg, TextBlock
from agentscope.model import ChatModelBase, DeepSeekChatModel, OpenAIChatModel
from agentscope.permission import PermissionBehavior
from agentscope.permission._decision import PermissionDecision
from agentscope.tool import FunctionTool, Toolkit

from ...domain.entities import Notice
from ...domain.ports import CompetitionRepositoryPort, NoticeSourcePort, SearchPort
from ...settings import ModelProfile
from ..cost import BudgetExceededError

# 发给模型的正文上限：通知全文可能很长，模型不需要逐字看完全文
MAX_NOTICE_CHARS = 4000

# 所有工具返回值的统一上限（M1 上下文管理第 1 层）。
# 工具结果会原样进入对话历史，一个失控的工具（比如读了个超大网页）
# 就能把上下文窗口挤爆、把 token 账单拉高。各工具可以按领域知识
# 自行截得更短（如通知正文 4000 字），这里是最后的安全网
MAX_TOOL_RESULT_CHARS = 4000

# 截断时追加的说明：告诉模型"下面没了"，它才会换个方式取信息
# （比如换个搜索词），而不是对着残缺内容硬编
TOOL_TRUNCATION_NOTICE = "\n…[工具结果过长，已被截断；如需更多信息请缩小询问范围]"

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


def build_chat_model(profile: ModelProfile, meter=None, recorder=None,
                     stream: bool = False) -> ChatModelBase:
    """按模型档案创建 AgentScope 的聊天模型客户端。

    密钥缺失在这里立刻报错，错误信息直接告诉用户该设置哪个环境变量。
    传入 meter（CostMeter）时，返回的是包了计价器的代理模型：
    每轮调用前查预算、调用后记账——框架对此完全无感。
    M2 起可再传 recorder（TaskRecorder），代理同时记会话事件。

    stream：是否真流式（M7+）。批处理任务（生成材料/识别）保持 False——
    一次拿整块简单可靠；聊天界面要"打字机"效果，传 True，
    框架的 reply_stream 才能逐字发 TextBlockDeltaEvent。
    """
    api_key = profile.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            f"模型档案 '{profile.name}' 缺少密钥：请设置环境变量 {profile.api_key_env}"
            f"（建议写进项目根目录的 .env 文件，该文件已被 gitignore，不会入库）"
        )

    if "deepseek" in profile.base_url:
        inner = DeepSeekChatModel(
            credential=DeepSeekCredential(api_key=api_key, base_url=profile.base_url),
            model=profile.model,
            stream=stream,
            max_retries=2,
        )
    else:
        # 其他 OpenAI 兼容服务商（如通义千问）走通用 OpenAI 协议
        inner = OpenAIChatModel(
            credential=OpenAICredential(api_key=api_key, base_url=profile.base_url),
            model=profile.model,
            stream=stream,
            max_retries=2,
        )
    # 没配计价器就返回裸模型，行为与 v1.5 完全一致
    if meter is None and recorder is None:
        return inner
    return MeteredChatModel(inner, meter, recorder)


class MeteredChatModel:
    """模型客户端的"计价代理"（M1）：包住真正的模型，调用前后各加一步。

    为什么用代理而不改 AgentScope 源码？——代理模式（类比 Java 的
    动态代理/AOP 切面）：在不改动被包对象的前提下，给所有调用
    统一加上"前置检查 + 后置记账"。框架拿到它照常用，因为 Agent
    只按鸭子类型调 __call__ / count_tokens 这几个方法（见模块 docstring 第 3 点）。

    M2 起可选携带 TaskRecorder：每次模型调用、每次压缩都记一条事件，
    sai replay 由此回放任务轨迹。

    已知缺口（刻意接受，见 ADR-003）：框架做上下文压缩时内部另发的
    摘要调用不经过本代理的 __call__，那几笔 token 暂不进台账。
    """

    def __init__(self, inner: ChatModelBase, meter, recorder=None):
        # meter 是 application/cost.py 的 CostMeter（不标类型，理由见 build_chat_model）
        self._inner = inner
        self._meter = meter
        self._recorder = recorder

    @property
    def context_size(self) -> int:
        """模型上下文窗口大小——框架算压缩阈值（trigger_ratio × 窗口）要用。"""
        return self._inner.context_size

    async def __call__(self, messages: list, tools: list | None = None, **kwargs):
        """每轮模型调用的总入口：先过预算闸，再真调用，最后记账。

        两种返回形态（内层模型 stream 开关决定，代理都兼容）：
        - 非流式：ChatResponse 整块 → 现拿现记；
        - 流式：async generator（增量 chunk）→ 包一层透传，
          usage 由服务商放在最后一个 chunk（stream_options include_usage），
          流耗尽时记一次账——语义仍是"调用完成后记账"。
        """
        # 前置熔断：上一轮把钱花满了，这一轮直接拦下（抛 BudgetExceededError，
        # 框架会把异常记为本次 reply 的 error，任务带着明确原因终止）
        self._meter.precheck()
        response = await self._inner(messages, tools=tools, **kwargs)

        if hasattr(response, "__aiter__"):
            # 流式形态：透传每个增量 chunk，尾巴上统一记账
            return self._metered_stream(response, messages)

        # 非流式：响应是 ChatResponse 对象，直接读 usage 字段
        usage = getattr(response, "usage", None)
        if usage is not None:
            self._meter.record(
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
            )
        # 会话事件：这一轮模型调用（正文太长只存摘要，完整轨迹的价值在
        # "哪一步、用了多少 token、输出了什么类型的块"，不在逐字存档）
        if self._recorder is not None:
            block_types = [type(b).__name__ for b in getattr(response, "content", []) or []]
            self._recorder.log(
                "model_call",
                messages=len(messages) if messages else 0,
                input_tokens=getattr(usage, "input_tokens", None) if usage else None,
                output_tokens=getattr(usage, "output_tokens", None) if usage else None,
                blocks=block_types,
            )
        return response

    async def _metered_stream(self, agen, messages: list):
        """包住流式返回：chunk 原样透传给框架（逐字事件靠它），
        同时盯着 usage（尾 chunk 才有）和块类型，流结束统一记账/记事件。"""
        usage = None
        block_types: list[str] = []
        async for chunk in agen:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = chunk_usage
            block_types = [type(b).__name__ for b in getattr(chunk, "content", []) or []]
            yield chunk
        if usage is not None:
            self._meter.record(
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
            )
        if self._recorder is not None:
            self._recorder.log(
                "model_call",
                messages=len(messages) if messages else 0,
                input_tokens=getattr(usage, "input_tokens", None) if usage else None,
                output_tokens=getattr(usage, "output_tokens", None) if usage else None,
                blocks=block_types,
            )

    async def count_tokens(self, messages: list, tools: list | None = None) -> int:
        """透传 token 估算（框架用它判断"该不该压缩"）。"""
        return await self._inner.count_tokens(messages, tools)

    async def generate_structured_output(self, *args, **kwargs):
        """透传结构化输出；框架压缩上下文走这里——记一条压缩事件。"""
        if self._recorder is not None:
            self._recorder.log("compression", note="上下文超过阈值，框架开始生成摘要")
        return await self._inner.generate_structured_output(*args, **kwargs)

    def __getattr__(self, name: str):
        """其余属性一律转给被包的真模型（stream、model_name 等）。

        注意 Python 细节：__getattr__ 只在"正常属性找不到"时才被调用，
        所以 self._inner / self._meter 的访问不会绕进这里造成死循环。
        """
        return getattr(self._inner, name)


def _with_truncation(func: Callable[..., str]) -> Callable[..., str]:
    """给工具函数套上"统一截断"外壳（M1 上下文管理第 1 层）。

    @wraps(func) 会把原函数的名字、docstring、类型标注都抄给包装函数——
    这一步不能省：AgentScope 靠这些元信息生成给模型看的工具说明书，
    丢了它们，模型就"看不懂"工具了。
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        if isinstance(result, str) and len(result) > MAX_TOOL_RESULT_CHARS:
            result = result[:MAX_TOOL_RESULT_CHARS] + TOOL_TRUNCATION_NOTICE
        return result

    return wrapper


def _with_recording(func: Callable[..., str], recorder) -> Callable[..., str]:
    """给工具函数套上"会话记录"外壳（M2）：每次调用记一条 tool_call 事件。

    截断壳在里、记录壳在外——存进会话的是"模型实际看到的结果"
    （截断后的），回放时才不会出现"存档说很长、模型其实只看到一半"的错位。
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        if recorder is not None:
            recorder.log(
                "tool_call",
                tool=func.__name__,
                args={k: str(v)[:200] for k, v in kwargs.items()},
                result=str(result)[:2000],
            )
        return result

    return wrapper


async def _add_tool(toolkit: Toolkit, func: Callable[..., str], recorder=None, gate=None) -> None:
    """注册工具的统一入口：按序套壳，最后以无人值守授权挂进工具箱。

    壳的顺序（从里到外）：截断 -> 权限门 -> 会话记录。
    - 权限门在截断之外：拒绝时短路，原函数和截断都不执行；
    - 记录在最外：模型实际收到的东西（含权限门的拒绝理由）都进轨迹，
      回放时看得到"模型被拦了"。
    所有工具都从这里过，保证壳一个不漏——
    如果各处直接调 toolkit.add_tool，很快就会有人忘了包外壳。
    """
    wrapped = _with_truncation(func)
    if gate is not None:
        wrapped = gate.wrap(wrapped)
    if recorder is not None:
        wrapped = _with_recording(wrapped, recorder)
    await toolkit.add_tool(FunctionTool(func=wrapped, permission=ALLOWED))


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
    recorder=None,
    gate=None,
) -> MaterialTools:
    """把三件工具注册进 AgentScope 的 Toolkit（异步：框架要求）。

    工具的说明书由 AgentScope 自动生成——从函数的 docstring 和
    类型标注提取，所以注释写得越清楚，模型用得越准。
    trace 列表由各闭包写入，跑完后供 CLI 播报"agent 干了什么"。
    recorder 不为 None 时，每次工具调用还会写一条会话事件（M2）。
    gate 不为 None 时，名单内的工具过权限门（M3）。
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
        # 统一入口注册：截断壳 + 权限门 + 记录壳 + 无人值守授权（见 _add_tool 注释）
        await _add_tool(tools.toolkit, func, recorder, gate)
    tools.functions = functions
    return tools


async def build_study_tools(
    search: SearchPort,
    competition_repository: CompetitionRepositoryPort,
    output_dir: Path,
    recorder=None,
    digest_llm=None,
    gate=None,
) -> MaterialTools:
    """备考路径任务的工具箱：联网搜索 + 读网页 + 落盘 + 查卡片（P5）。

    M3 起多一件 research_digest（研究分身）：它内部自己跑一遍
    "搜索 -> 精读 -> 单次结构化调用汇总"，只把千字摘要交还给主循环——
    主对话不再被几十页原文塞满。digest_llm 是分身专用的 LLM 客户端
    （结构和主循环同款，计价器/会话记录是同一个，花费合并算账）。
    """

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

    def research_digest(topic: str) -> str:
        """派"研究分身"调研一个主题：自动搜索 + 精读网页 + 汇总成带网址的调研摘要。
        topic 填研究主题（如 '蓝桥杯 备考经验'）。想快速了解一个主题时优先用它，
        比自己 search_web + read_page 逐页看省得多。"""
        from ..prompts import DIGEST_SCHEMA, DIGEST_SYSTEM_PROMPT

        tools.trace.append(f"research_digest({topic!r})")
        if digest_llm is None:
            return "研究分身未装配（缺少摘要模型），请改用 search_web + read_page 自己调研。"

        # 分身第 1 步：搜索，取前 3 条线索
        results = search.search(topic, top_k=3)
        if not results:
            return "搜索没有返回结果（可能网络波动），请换个搜索词重试。"

        # 分身第 2 步：精读前 2 个页面（每页最多 2000 字），拼成材料包
        materials = []
        for item in results[:2]:
            page = search.read_page(item["url"], max_chars=2000)
            materials.append(f"【来源】{item['title']}（{item['url']}）\n{page}")

        # 分身第 3 步：一次结构化调用，把材料压成摘要
        # （这就是"子代理"：分身有自己的输入输出，主循环永远看不到原文，只看摘要）
        digest = digest_llm.complete_structured(
            system=DIGEST_SYSTEM_PROMPT,
            user="\n\n".join(materials) + f"\n\n研究主题：{topic}",
            schema=DIGEST_SCHEMA,
        )

        # 分身第 4 步：把结构化摘要渲染成文本交还主循环
        lines = [f"【概述】{digest.get('summary', '')}"]
        for point in digest.get("key_points", []):
            lines.append(f"- {point}")
        urls = digest.get("useful_urls", [])
        if urls:
            lines.append("【有用网址】")
            lines.extend(f"  {u}" for u in urls)
        return "\n".join(lines)

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
        "research_digest": research_digest,
        "save_material": save_material,
        "list_competitions": list_competitions,
    }
    for func in functions.values():
        await _add_tool(tools.toolkit, func, recorder, gate)
    tools.functions = functions
    return tools


async def _run_material_agent_async(
    profile: ModelProfile,
    system_prompt: str,
    user_request: str,
    tools: MaterialTools,
    max_iters: int,
    meter=None,
    context_config: ContextConfig | None = None,
    recorder=None,
) -> AgentOutcome:
    """组装 Agent 并跑完一次材料生成任务（异步版）。

    meter / context_config / recorder 都是可选注入：
    - meter 有值 -> 模型客户端包上计价代理（预算熔断 + 记账）；
    - context_config 有值 -> 打开框架的自动上下文压缩（超阈值时
      把旧对话压成结构化摘要，长任务不再撑爆窗口）；
    - recorder 有值 -> 模型调用、压缩、工具调用、收尾都写会话事件（M2）。
    """
    if recorder is not None:
        recorder.log("user_input", text=user_request[:1000])
    agent = Agent(
        name="material_agent",
        system_prompt=system_prompt,
        model=build_chat_model(profile, meter, recorder),
        toolkit=tools.toolkit,
        react_config=ReActConfig(max_iters=max_iters),
        context_config=context_config,
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
    if recorder is not None:
        if reply.error is None:
            recorder.log("result", final_text=text)
        else:
            recorder.log("error", error=str(reply.error))
    return AgentOutcome(final_text=text, error=None if reply.error is None else str(reply.error))


def run_material_generation(
    profile: ModelProfile,
    system_prompt: str,
    user_request: str,
    tools_builder: Callable[[], Awaitable[MaterialTools]],
    max_iters: int = 8,
    meter=None,
    context_config: ContextConfig | None = None,
    recorder=None,
) -> tuple[AgentOutcome, MaterialTools]:
    """同步门面：建工具箱 -> 组 Agent -> 跑循环，返回结果和工具轨迹。

    tools_builder：零参数的异步函数，返回装好工具的 MaterialTools
    （异步是框架要求——add_tool 是异步方法）。材料生成和备考路径
    两个任务各自传入自己的工具箱构建器。
    meter / context_config / recorder：M1/M2 的可选注入，原样透传。
    用 asyncio.run 包装异步调用，让用例层和 CLI 保持同步代码风格。
    注意：未来 FastAPI 异步环境调用时要换成 await 版本（P6 处理）。
    """

    async def pipeline() -> tuple[AgentOutcome, MaterialTools]:
        tools = await tools_builder()
        outcome = await _run_material_agent_async(
            profile, system_prompt, user_request, tools, max_iters,
            meter=meter, context_config=context_config, recorder=recorder,
        )
        return outcome, tools

    return asyncio.run(pipeline())


# ---------- M4 差异化：聊天 agent（工具箱 + 事件流） ----------


async def build_chat_tools(
    source: NoticeSourcePort,
    notice_repository,
    competition_repository: CompetitionRepositoryPort,
    search: SearchPort,
    identify_usecase,
    sentinel,
    recorder=None,
    gate=None,
) -> MaterialTools:
    """聊天 agent 的工具箱：让它"自己动手"而不是教用户敲命令。

    六件工具对应聊天的典型意图：
    - list_competitions / query_deadlines：读库（查卡片、查截止）
    - get_notice_content：读某条通知的原文
    - search_web：联网搜索
    - scan_latest_notices：爬官网最新通知（零 LLM 成本）
    - identify_latest_notices：识别最新通知是否比赛（花 LLM，说明里写明）
    recorder/gate 与其他工具箱一致：记录壳 + 权限门。
    """

    tools = MaterialTools(toolkit=Toolkit())

    def list_competitions() -> str:
        """列出数据库里全部比赛卡片，含名称、类型、截止日期和通知链接。"""
        tools.trace.append("list_competitions()")
        cards = competition_repository.list_all()
        if not cards:
            return "库里还没有比赛卡片。可以让我 scan_latest_notices 去官网扫一扫。"
        lines = []
        for index, card in enumerate(cards, start=1):
            deadline = card.deadline.strftime("%Y-%m-%d") if card.deadline else "未写"
            lines.append(
                f"{index}. {card.name}（{card.type}，截止 {deadline}）  通知：{card.notice_url}"
            )
        return "\n".join(lines)

    def get_notice_content(notice_url: str) -> str:
        """读取一条比赛通知的正文原文。notice_url 填通知详情页的完整网址。"""
        tools.trace.append(f"get_notice_content({notice_url})")
        notice = source.fetch_detail(Notice(source_url=notice_url, title=""))
        if not notice.content:
            return "这条通知没有抓到正文（可能是图片/外链形式）。"
        return notice.content[:MAX_NOTICE_CHARS]

    def search_web(query: str, max_results: int = 5) -> str:
        """联网搜索资料。query 填搜索词，返回带网址的结果列表。"""
        tools.trace.append(f"search_web({query!r})")
        results = search.search(query, top_k=max_results)
        if not results:
            return "搜索暂时没有返回结果（可能网络波动），请换个搜索词重试。"
        lines = []
        for index, item in enumerate(results, start=1):
            lines.append(f"{index}. {item['title']}\n   网址：{item['url']}\n   摘要：{item['snippet']}")
        return "\n".join(lines)

    def query_deadlines() -> str:
        """查询临近截止的比赛（未来 30 天，按紧迫度排序）。"""
        tools.trace.append("query_deadlines()")
        alerts = sentinel.upcoming(within_days=30)
        if not alerts:
            return "未来 30 天没有临近截止的比赛。"
        lines = []
        for alert in alerts:
            deadline_str = alert.card.deadline.strftime("%Y-%m-%d")
            lines.append(f"- {alert.label}｜{alert.card.name}（截止 {deadline_str}）")
        return "\n".join(lines)

    def scan_latest_notices(limit: int = 8) -> str:
        """爬一遍学院官网，拉取最新通知列表（只爬取不识别，零 LLM 成本）。
        limit 填要看的条数。想判断哪些是比赛，接着调用 identify_latest_notices。"""
        tools.trace.append(f"scan_latest_notices({limit})")
        notices = source.list_notices(limit=limit)
        if not notices:
            return "官网没有抓到通知（列表页为空或结构变了？）"
        lines = []
        for index, notice in enumerate(notices, start=1):
            date_str = notice.published_at.strftime("%Y-%m-%d") if notice.published_at else "????-??-??"
            lines.append(f"{index}. [{date_str}] {notice.title}\n   {notice.source_url}")
        return "\n".join(lines)

    def identify_latest_notices(limit: int = 3) -> str:
        """识别最新通知里哪些是比赛（粗筛 + LLM 结构化调用，会产生费用）。
        limit 填要识别的条数（默认 3，最多 10）。返回每条的判定与卡片。"""
        tools.trace.append(f"identify_latest_notices({limit})")
        outcomes = identify_usecase.execute(limit=max(1, min(limit, 10)))
        comp = sum(1 for o in outcomes if o.is_competition)
        lines = [f"共 {len(outcomes)} 条：比赛 {comp} 条。"]
        for o in outcomes:
            mark = "[比赛]" if o.is_competition else "[非比赛]"
            lines.append(f"- {mark}｜{o.notice.title}")
            if o.competition is not None:
                deadline = o.competition.deadline.strftime("%Y-%m-%d") if o.competition.deadline else "见通知"
                lines.append(f"  {o.competition.name}（{o.competition.type}，截止 {deadline}）")
        if identify_usecase.budget_error:
            lines.append(f"注意：{identify_usecase.budget_error}")
        return "\n".join(lines)

    functions = {
        "list_competitions": list_competitions,
        "get_notice_content": get_notice_content,
        "search_web": search_web,
        "query_deadlines": query_deadlines,
        "scan_latest_notices": scan_latest_notices,
        "identify_latest_notices": identify_latest_notices,
    }
    for func in functions.values():
        await _add_tool(tools.toolkit, func, recorder, gate)
    tools.functions = functions
    return tools


async def run_chat_agent_stream(
    profile: ModelProfile,
    meter,
    system_prompt: str,
    history: list[dict],
    user_text: str,
    tools: MaterialTools,
    max_iters: int = 12,
    model: ChatModelBase | None = None,
):
    """跑一次聊天 agent 循环，把框架事件流翻译成聊天帧（异步生成器）。

    帧协议（与 /api/chat 的 SSE 帧一致）：
        {"type": "token", "text": …}   逐字增量
        {"type": "tool", "name": …}    模型发起了一次工具调用
        {"type": "done", "reply": …}   完成，带完整回复文本
    框架会把模型/工具的异常捕获进最终 Msg.error，这里转成 done.error。
    model 可注入（测试塞假模型离线跑）；默认按档案现建并包计价代理。
    """
    from agentscope.event import TextBlockDeltaEvent, ToolCallStartEvent

    # 聊天要"打字机"：真流式（stream=True），框架才逐字发 TextBlockDeltaEvent。
    # 注意 meter 只在这一层 MeteredChatModel 生效——build_chat_model 传 None
    # 拿裸模型（修复：此前内外各包一层，聊天每轮记账双倍）。
    inner = model or build_chat_model(profile, meter=None, stream=True)
    agent = Agent(
        name="chat_agent",
        system_prompt=system_prompt,
        model=MeteredChatModel(inner, meter),
        toolkit=tools.toolkit,
        react_config=ReActConfig(max_iters=max_iters),
    )
    # 多轮上下文：把最近几轮拼成 user/assistant 交替的消息列表 + 当前这条
    inputs = [
        Msg(name=m["role"], role=m["role"],
            content=[TextBlock(type="text", text=m["content"])])
        for m in history
    ]
    inputs.append(Msg(name="user", role="user",
                      content=[TextBlock(type="text", text=user_text)]))

    collected: list[str] = []
    try:
        async for event in agent.reply_stream(inputs):
            if isinstance(event, TextBlockDeltaEvent):
                collected.append(event.delta)
                yield {"type": "token", "text": event.delta}
            elif isinstance(event, ToolCallStartEvent):
                yield {"type": "tool", "name": event.tool_call_name}
            elif isinstance(event, Msg):
                if getattr(event, "error", None) is not None:
                    yield {"type": "done", "reply": "".join(collected),
                           "error": str(event.error)}
                    return
    except BudgetExceededError as error:
        # 计价代理在模型调用前熔断：预算信号转成 done.error 给前端
        yield {"type": "done", "reply": "".join(collected), "error": str(error)}
        return

    yield {"type": "done", "reply": "".join(collected)}
