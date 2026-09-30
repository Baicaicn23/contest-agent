"""M1 验收测试：成本台账、模型路由、预算闸门、上下文管理，全程不碰网络不花钱。

分层手法与 P2-P5 一致：
- 纯函数（算钱、截断）直接测；
- CostMeter / CostReport 用假仓储测业务规则；
- SqliteUsageRepository 用内存库测真 SQL；
- OpenAiCompatLlm 用"假 openai 客户端"测记账（不发真请求）；
- MeteredChatModel 用假内部模型测代理的记账与熔断；
- agent 循环压缩用"鸭子类型假模型 + 小窗口"测自动压缩真的会发生。
真实调用 DeepSeek 的验收标了 live，默认不跑（见 pyproject addopts）。
"""

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from contest_agent.application.cost import (
    BudgetExceededError,
    CostMeter,
    compute_cost_yuan,
)
from contest_agent.application.harness.agent_factory import (
    MAX_TOOL_RESULT_CHARS,
    TOOL_TRUNCATION_NOTICE,
    MeteredChatModel,
    _with_truncation,
)
from contest_agent.application.usecases.cost_report import CostReport
from contest_agent.application.usecases.identify_competitions import (
    IdentifyCompetitions,
)
from contest_agent.domain.entities import Competition, Notice, UsageEntry
from contest_agent.infrastructure.llm.openai_compat import OpenAiCompatLlm
from contest_agent.infrastructure.persistence.repository import SqliteUsageRepository
from contest_agent.settings import (
    ModelProfile,
    Settings,
    YamlConfig,
    load_settings,
    load_yaml_config,
)


# ---------- 通用假对象 ----------


class FakeUsageRepo:
    """假台账仓储：字典列表假装数据库，测业务规则零成本。"""

    def __init__(self) -> None:
        self.entries: list[UsageEntry] = []

    def record(self, entry: UsageEntry) -> None:
        self.entries.append(entry)

    def list_entries(
        self, task_type: str | None = None, on_date: date | None = None
    ) -> list[UsageEntry]:
        result = []
        for entry in self.entries:
            if task_type is not None and entry.task_type != task_type:
                continue
            if on_date is not None and (
                entry.created_at is None or entry.created_at.date() != on_date
            ):
                continue
            result.append(entry)
        return result


def _profile(name: str = "deepseek", **prices) -> ModelProfile:
    """造一个测试用模型档案（单价可选）。"""
    return ModelProfile(
        name=name,
        base_url="https://api.example.com",
        api_key_env="EXAMPLE_API_KEY",
        model=f"{name}-chat",
        **prices,
    )


# ---------- 算钱纯函数 ----------


def test_compute_cost_yuan_full_prices() -> None:
    """1 百万输入 + 0.5 百万输出，单价 2/8 元 -> 2 + 4 = 6 元。"""
    cost = compute_cost_yuan(1_000_000, 500_000, input_price_per_m=2.0, output_price_per_m=8.0)
    assert cost == pytest.approx(6.0)


def test_compute_cost_yuan_missing_price_returns_none() -> None:
    """任一单价没配就返回 None——宁可显示未知，不编数字。"""
    assert compute_cost_yuan(100, 100, None, 8.0) is None
    assert compute_cost_yuan(100, 100, 2.0, None) is None


# ---------- CostMeter：记账 + 熔断 ----------


def test_cost_meter_records_entry_and_accumulates() -> None:
    repo = FakeUsageRepo()
    meter = CostMeter(
        profile=_profile(input_price_per_m=2.0, output_price_per_m=8.0),
        task_type="identify",
        repository=repo,
        note="limit=10",
    )
    meter.precheck()  # 没配预算：precheck 永远放行
    meter.record(prompt_tokens=1_000_000, completion_tokens=500_000)

    assert meter.call_count == 1
    assert meter.spent_yuan == pytest.approx(6.0)
    assert len(repo.entries) == 1
    entry = repo.entries[0]
    assert entry.task_type == "identify"
    assert entry.profile_name == "deepseek"
    assert entry.model == "deepseek-chat"
    assert entry.cost_yuan == pytest.approx(6.0)
    assert entry.note == "limit=10"


def test_cost_meter_unpriced_profile_still_records_tokens() -> None:
    """没配单价：费用记 None，但 token 照记——量必须可见。"""
    repo = FakeUsageRepo()
    meter = CostMeter(profile=_profile(), task_type="generate", repository=repo)
    cost = meter.record(prompt_tokens=100, completion_tokens=200)
    assert cost is None
    assert meter.spent_yuan == 0.0
    assert repo.entries[0].prompt_tokens == 100


def test_cost_meter_budget_breaks_before_call() -> None:
    """熔断时序：打穿预算的那笔照常入账（钱已花、响应已到手），
    但下一笔调用在 precheck 就被拦下——一个子儿都不再多花。"""
    meter = CostMeter(
        profile=_profile(input_price_per_m=2.0, output_price_per_m=8.0),
        task_type="identify",
        budget_yuan=5.0,
    )
    meter.record(prompt_tokens=1_000_000, completion_tokens=500_000)  # 6 元 > 5 元
    assert meter.spent_yuan == pytest.approx(6.0)  # 花掉的钱必须在账上

    # 第二次调用在 precheck 就被拦
    with pytest.raises(BudgetExceededError):
        meter.precheck()


# ---------- SqliteUsageRepository：真 SQL（内存库） ----------


def test_usage_repository_roundtrip_and_filters() -> None:
    repo = SqliteUsageRepository("sqlite:///:memory:")
    base = datetime(2026, 9, 30, 10, 0, 0)
    repo.record(
        UsageEntry("identify", "deepseek", "deepseek-chat", 100, 20, 0.0004, created_at=base)
    )
    repo.record(
        UsageEntry("generate", "deepseek", "deepseek-chat", 5000, 3000, 0.034, created_at=base)
    )
    repo.record(
        UsageEntry("identify", "qwen", "qwen-plus", 80, 10, None,
                   created_at=datetime(2026, 10, 1, 9, 0, 0))
    )

    assert len(repo.list_entries()) == 3
    identify = repo.list_entries(task_type="identify")
    assert len(identify) == 2
    today = repo.list_entries(on_date=date(2026, 9, 30))
    assert len(today) == 2
    both = repo.list_entries(task_type="identify", on_date=date(2026, 9, 30))
    assert len(both) == 1
    assert both[0].model == "deepseek-chat"


# ---------- OpenAiCompatLlm：结构化调用记账 ----------


class _StubUsage:
    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion


class _StubMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubChoice:
    def __init__(self, content: str) -> None:
        self.message = _StubMessage(content)


class _StubResponse:
    def __init__(self, content: str, usage: _StubUsage | None) -> None:
        self.choices = [_StubChoice(content)]
        self.usage = usage


class _StubOpenAiClient:
    """假 openai 客户端：接口形状与真客户端一致，额外回报 usage。"""

    def __init__(self, usage: _StubUsage) -> None:
        self._usage = usage
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs) -> _StubResponse:
        self.calls += 1
        return _StubResponse('{"is_competition": false, "reason": "不是比赛"}', self._usage)


def test_openai_llm_records_usage_via_meter(monkeypatch) -> None:
    monkeypatch.setenv("EXAMPLE_API_KEY", "test-key")  # 构造时的密钥检查要过
    repo = FakeUsageRepo()
    meter = CostMeter(
        profile=_profile(input_price_per_m=2.0, output_price_per_m=8.0),
        task_type="identify",
        repository=repo,
    )
    llm = OpenAiCompatLlm(_profile(input_price_per_m=2.0, output_price_per_m=8.0),
                          client=_StubOpenAiClient(_StubUsage(1000, 100)),
                          meter=meter)
    llm.complete_structured(system="s", user="u", schema={})

    assert meter.call_count == 1
    assert meter.spent_yuan == pytest.approx(1000 / 1e6 * 2 + 100 / 1e6 * 8)
    assert repo.entries[0].prompt_tokens == 1000


def test_openai_llm_budget_blocks_before_request(monkeypatch) -> None:
    """预算花满后，请求根本不会发出去（假客户端计数为 0 次新增）。"""
    monkeypatch.setenv("EXAMPLE_API_KEY", "test-key")
    meter = CostMeter(
        profile=_profile(input_price_per_m=2.0, output_price_per_m=8.0),
        task_type="identify",
        budget_yuan=0.001,
    )
    client = _StubOpenAiClient(_StubUsage(10**9, 10**9))
    llm = OpenAiCompatLlm(_profile(input_price_per_m=2.0, output_price_per_m=8.0),
                          client=client, meter=meter)
    llm.complete_structured(system="s", user="u", schema={})  # 第一笔打穿预算（照常入账）
    with pytest.raises(BudgetExceededError):
        llm.complete_structured(system="s", user="u", schema={})  # 第二笔发出前被拦
    assert client.calls == 1  # 第二次请求没发出去


# ---------- MeteredChatModel：agent 循环的计价代理 ----------


class _FakeInnerChatModel:
    """假内部模型：返回带 usage 的 ChatResponse，可编程熔断场景。"""

    context_size = 32768
    stream = False
    model = "fake"
    formatter = SimpleNamespace(supported_input_media_types=["image/*"])

    def __init__(self, usage) -> None:
        self._usage = usage
        self.calls = 0

    async def __call__(self, messages, tools=None, **kwargs):
        self.calls += 1
        from agentscope.message import TextBlock
        from agentscope.model import ChatResponse

        return ChatResponse(
            content=[TextBlock(type="text", text="完成。")],
            is_last=True,
            usage=self._usage,
        )

    async def count_tokens(self, messages, tools=None) -> int:
        return 10

    async def generate_structured_output(self, *args, **kwargs):
        return SimpleNamespace(content={})


def test_metered_chat_model_records_each_call() -> None:
    from agentscope.model import ChatUsage

    repo = FakeUsageRepo()
    meter = CostMeter(
        profile=_profile(input_price_per_m=2.0, output_price_per_m=8.0),
        task_type="generate",
        repository=repo,
    )
    inner = _FakeInnerChatModel(ChatUsage(input_tokens=800, output_tokens=200, time=0.1))
    proxied = MeteredChatModel(inner, meter)

    # 鸭子类型代理：context_size / formatter 等属性照常透传
    assert proxied.context_size == 32768
    assert proxied.formatter is inner.formatter

    # 模拟 agent 循环里的两轮调用
    import asyncio

    asyncio.run(proxied([], None))
    asyncio.run(proxied([], None))

    assert inner.calls == 2
    assert meter.call_count == 2
    assert meter.spent_yuan == pytest.approx(2 * (800 / 1e6 * 2 + 200 / 1e6 * 8))
    assert len(repo.entries) == 2


def test_metered_chat_model_breaks_budget_mid_loop() -> None:
    """循环中途预算打穿：下一轮模型调用在发出前被代理拦下。"""
    from agentscope.message import TextBlock
    from agentscope.model import ChatResponse, ChatUsage

    meter = CostMeter(
        profile=_profile(input_price_per_m=2.0, output_price_per_m=8.0),
        task_type="generate",
        budget_yuan=0.0001,  # 极小预算：一轮就打穿
    )
    inner = _FakeInnerChatModel(ChatUsage(input_tokens=10**6, output_tokens=10**5, time=0.1))
    proxied = MeteredChatModel(inner, meter)

    import asyncio

    asyncio.run(proxied([], None))  # 第一轮：打穿预算（照常入账）
    with pytest.raises(BudgetExceededError):
        asyncio.run(proxied([], None))  # 第二轮：precheck 拦下
    assert inner.calls == 1


# ---------- CostReport：账单汇总 ----------


def test_cost_report_aggregates_by_task_and_model() -> None:
    repo = FakeUsageRepo()
    repo.record(UsageEntry("identify", "deepseek", "deepseek-chat", 1000, 500, 0.006))
    repo.record(UsageEntry("identify", "deepseek", "deepseek-chat", 2000, 300, 0.0064))
    repo.record(UsageEntry("generate", "qwen", "qwen-plus", 8000, 4000, 0.0144))

    summary = CostReport(repo).execute()

    assert summary.total.calls == 3
    assert summary.total.cost_yuan == pytest.approx(0.006 + 0.0064 + 0.0144)
    assert summary.by_task["identify"].calls == 2
    assert summary.by_task["identify"].cost_yuan == pytest.approx(0.0124)
    assert summary.by_model["qwen-plus"].calls == 1

    filtered = CostReport(repo).execute(task_type="generate")
    assert filtered.total.calls == 1


def test_cost_report_unpriced_entry_makes_cost_unknown() -> None:
    """账组里混进一笔没算出钱的流水：整组费用如实标 None，不给假总数。"""
    repo = FakeUsageRepo()
    repo.record(UsageEntry("identify", "deepseek", "deepseek-chat", 100, 10, 0.00028))
    repo.record(UsageEntry("identify", "qwen", "qwen-plus", 100, 10, None))

    summary = CostReport(repo).execute()
    assert summary.total.cost_yuan is None
    assert summary.total.calls == 2


# ---------- 模型路由（settings.profile_for_task） ----------


def _yaml_with_routing(routing: dict) -> YamlConfig:
    return YamlConfig(
        active_model="deepseek",
        models={
            "deepseek": ModelProfile(
                name="deepseek", base_url="https://api.deepseek.com",
                api_key_env="DEEPSEEK_API_KEY", model="deepseek-chat",
            ),
            "qwen": ModelProfile(
                name="qwen", base_url="https://example.com",
                api_key_env="QWEN_API_KEY", model="qwen-plus",
            ),
        },
        sources=[],
        routing=routing,
    )


def test_profile_for_task_routes_by_config() -> None:
    settings = Settings(
        database_url="sqlite:///:memory:",
        active_model="deepseek",
        yaml_config=_yaml_with_routing({"identify": "qwen"}),
    )
    # identify 被路由到便宜档案 qwen；generate 没配 -> 用 active_model 兜底
    assert settings.profile_for_task("identify").name == "qwen"
    assert settings.profile_for_task("generate").name == "deepseek"


def test_profile_for_task_rejects_unknown_profile() -> None:
    settings = Settings(
        database_url="sqlite:///:memory:",
        active_model="deepseek",
        yaml_config=_yaml_with_routing({"generate": "不存在的档案"}),
    )
    with pytest.raises(KeyError):
        settings.profile_for_task("generate")


# ---------- 预算闸门：identify 用例保留部分结果 ----------


class FakeSource:
    """假爬虫：吐出指定数量的通知（无正文 -> 粗筛命中后会触发补详情）。"""

    def __init__(self, titles: list[str]) -> None:
        self._titles = titles

    def list_notices(self, limit: int = 10) -> list[Notice]:
        return [Notice(source_url=f"u{i}", title=t) for i, t in enumerate(self._titles)]

    def fetch_detail(self, notice: Notice) -> Notice:
        notice.content = "竞赛报名，截止 2026-12-31"
        return notice


class BudgetBreakLlm:
    """假 LLM：第一次正常返回，第二次抛预算熔断（模拟计价器拦截）。"""

    def __init__(self) -> None:
        self.calls = 0

    def complete_structured(self, system: str, user: str, schema: dict) -> dict:
        self.calls += 1
        if self.calls >= 2:
            raise BudgetExceededError("预算熔断：任务 'identify' 已花费 5.0000 元")
        return {
            "is_competition": True,
            "name": "蓝桥杯",
            "type": "exam",
            "deadline": "2026-12-31",
            "evidence": "竞赛报名",
            "reason": "是比赛",
        }


class FakeCardRepo:
    def __init__(self) -> None:
        self.saved: list[Competition] = []

    def save_if_absent(self, competition: Competition) -> bool:
        self.saved.append(competition)
        return True

    def list_all(self) -> list[Competition]:
        return list(self.saved)


def test_identify_budget_break_preserves_partial_results() -> None:
    """两条通知、第二条触发熔断：第一条的卡片必须照常入库并返回。"""
    llm = BudgetBreakLlm()
    store = FakeCardRepo()
    usecase = IdentifyCompetitions(
        FakeSource(["比赛A", "比赛B"]), llm, store
    )
    outcomes = usecase.execute(limit=2)

    assert llm.calls == 2                      # 第二条确实尝试了
    assert len(outcomes) == 1                  # 但只有第一条的结果
    assert outcomes[0].competition.name == "蓝桥杯"
    assert usecase.budget_error is not None    # 熔断原因存档，CLI 要播报
    assert "预算熔断" in usecase.budget_error
    assert len(store.saved) == 1               # 已花钱识别出的卡片已入库


# ---------- 上下文管理：工具结果统一截断 ----------


def test_truncation_wrapper_cuts_long_results() -> None:
    @_with_truncation
    def big_tool() -> str:
        """返回超长文本的工具。"""
        return "字" * (MAX_TOOL_RESULT_CHARS + 100)

    result = big_tool()
    assert len(result) == MAX_TOOL_RESULT_CHARS + len(TOOL_TRUNCATION_NOTICE)
    assert result.endswith(TOOL_TRUNCATION_NOTICE)


def test_truncation_wrapper_passes_short_results() -> None:
    @_with_truncation
    def small_tool() -> str:
        """返回短文本的工具。"""
        return "短结果"

    assert small_tool() == "短结果"


def test_truncation_wrapper_preserves_metadata() -> None:
    """@wraps 必须保住名字/docstring/类型标注——AgentScope 生成工具说明书全靠它们。"""

    @_with_truncation
    def documented_tool(filename: str, count: int) -> str:
        """读取一个文件。filename 是文件名，count 是行数。"""
        return "x"

    assert documented_tool.__name__ == "documented_tool"
    assert "读取一个文件" in documented_tool.__doc__
    assert documented_tool.__annotations__ == {"filename": str, "count": int, "return": str}


# ---------- 上下文管理：agent 循环自动压缩（框架能力，离线验证接线） ----------


class FakeLoopChatModel:
    """鸭子类型假模型：模拟"第一轮调工具 -> 第二轮收尾"的两轮循环。

    context_size 的取值是精心卡的（这是本测试最微妙的一处）——
    框架的压缩有两道闸，三个数必须排成"阈值 < 上下文量 < 窗口"：
    1. 触发闸：上下文估算必须超过 trigger_ratio x context_size
       （0.8 x 16000 = 12800 < 约 14100 的工具结果）；
    2. 摘要闸：待压缩内容 + 压缩提示词本身不能再超过窗口
       （约 15000 < 16000），否则框架静默降级为"截断"而不是摘要
       （compression_fallback_to_truncation，默认开）。
    """

    context_size = 16000
    stream = False
    model = "fake-model"
    formatter = SimpleNamespace(supported_input_media_types=["image/*"])

    def __init__(self) -> None:
        self.calls = 0
        self.structured_calls = 0  # 压缩摘要调用的次数（>0 说明压缩真的发生了）

    async def __call__(self, messages, tools=None, **kwargs):
        from agentscope.message import TextBlock, ToolCallBlock
        from agentscope.model import ChatResponse, ChatUsage

        self.calls += 1
        if self.calls == 1:
            # 第一轮：发起工具调用，把超长结果灌进上下文
            return ChatResponse(
                content=[ToolCallBlock(id="call_1", name="big_note", input="{}")],
                is_last=True,
                usage=ChatUsage(input_tokens=50, output_tokens=5, time=0.01),
            )
        # 第二轮：收尾陈述
        return ChatResponse(
            content=[TextBlock(type="text", text="任务完成。")],
            is_last=True,
            usage=ChatUsage(input_tokens=300, output_tokens=5, time=0.01),
        )

    async def count_tokens(self, messages, tools=None) -> int:
        """字符级粗估（中文近似 1 字 1 token），够测试用。

        两个容易漏的地方（第一版假模型各栽过一次）：
        - 工具结果的文本在 ToolResultBlock.output 里，而且可能是
          "TextBlock 列表"而不是纯字符串，要拆开数；
        - tools 的 JSON schema 也占 token，一并计入。
        """
        total = 0
        for msg in messages:
            for block in msg.get_content_blocks():
                for attr in ("text", "input", "thinking"):
                    value = getattr(block, attr, None)
                    if isinstance(value, str):
                        total += len(value)
                output = getattr(block, "output", None)
                if isinstance(output, str):
                    total += len(output)
                elif isinstance(output, list):
                    for item in output:
                        text = getattr(item, "text", None)
                        if isinstance(text, str):
                            total += len(text)
        if tools:
            total += len(json.dumps(tools, ensure_ascii=False))
        return total

    async def generate_structured_output(self, messages, structured_model, **kwargs):
        """压缩摘要调用：返回框架要的 StructuredResponse（带五个摘要字段）。

        注意返回类型不能偷懒用 SimpleNamespace——框架还会读
        finished_reason 判断是否被中断（第一版假模型就栽在这）。
        """
        from agentscope.model import StructuredResponse

        self.structured_calls += 1
        return StructuredResponse(content={
            "task_overview": "读取超长通知并汇报",
            "current_state": "已读取通知正文",
            "important_discoveries": "通知内容很长",
            "next_steps": "汇报完成",
            "context_to_preserve": "无",
        })


def test_agent_loop_auto_compresses_when_over_threshold() -> None:
    """超长工具结果 + 小窗口：框架在第二轮推理前自动压缩，任务不失败。

    这是对 M1 上下文管理的端到端离线验证：
    ContextConfig（我们配置的阈值）-> compress_context（框架自动触发）
    -> generate_structured_output（摘要生成）-> 上下文缩回阈值内。
    （项目没装 pytest-asyncio，统一用 asyncio.run 包同步测试。）
    """
    import asyncio

    asyncio.run(_run_compress_scenario())


async def _run_compress_scenario() -> None:
    from agentscope.agent import Agent, ContextConfig, ReActConfig
    from agentscope.message import Msg, TextBlock
    from agentscope.tool import FunctionTool, Toolkit

    from contest_agent.application.harness.agent_factory import ALLOWED

    def big_note() -> str:
        """返回一篇超长的比赛通知正文。"""
        # 约 14000 字：故意不套 _with_truncation 截断壳——本测试验证的是
        # "上下文超限后框架自动压缩"，不是截断壳（截断壳有自己的单测）。
        # 窗口 16000 x 0.8 = 12800 阈值 < 14000 结果 < 16000 窗口，见类 docstring
        return "比赛通知正文，包含大量细节。" * 1000

    toolkit = Toolkit()
    await toolkit.add_tool(FunctionTool(func=big_note, permission=ALLOWED))

    fake_model = FakeLoopChatModel()
    meter = CostMeter(profile=_profile(), task_type="generate")
    agent = Agent(
        name="compress_test_agent",
        system_prompt="你是测试助手，读完通知就汇报。",
        model=MeteredChatModel(fake_model, meter),
        toolkit=toolkit,
        react_config=ReActConfig(max_iters=5),
        context_config=ContextConfig(trigger_ratio=0.8),
    )
    reply = await agent.reply(
        Msg(name="user", role="user", content=[TextBlock(type="text", text="请读通知并汇报")])
    )

    # 1) 任务正常完成（压缩没有把任务搞挂）
    assert reply.error is None
    # 2) 压缩真的发生了：摘要被生成并写进了 state
    assert fake_model.structured_calls == 1
    assert agent.state.summary
    assert "已读取通知正文" in agent.state.summary
    # 3) 两轮模型调用都经过了计价代理
    assert meter.call_count == 2


# ---------- 配置与 CLI ----------


def _minimal_yaml_config() -> YamlConfig:
    return _yaml_with_routing({})


def test_budget_env_override(monkeypatch) -> None:
    """BUDGET_PER_TASK_YUAN 环境变量覆盖 yaml 预算；设 0 表示关闭。"""
    import contest_agent.settings as settings_module

    monkeypatch.setattr(settings_module, "load_yaml_config", lambda path=None: _minimal_yaml_config())
    monkeypatch.setattr(settings_module, "load_dotenv", lambda: None)

    monkeypatch.setenv("BUDGET_PER_TASK_YUAN", "5")
    settings_module.load_settings.cache_clear()
    assert load_settings().budget_per_task_yuan == 5.0

    monkeypatch.setenv("BUDGET_PER_TASK_YUAN", "0")
    settings_module.load_settings.cache_clear()
    assert load_settings().budget_per_task_yuan is None

    monkeypatch.delenv("BUDGET_PER_TASK_YUAN")
    settings_module.load_settings.cache_clear()
    assert load_settings().budget_per_task_yuan is None

    settings_module.load_settings.cache_clear()  # 还原缓存，别污染别的测试


def test_sai_cost_command_prints_bill(monkeypatch, capsys) -> None:
    """sai cost：拿假用例替换装配，验证账单播报的格式与范围说明。"""
    import contest_agent.composition as composition_module
    import contest_agent.presentation.cli as cli_module

    class FakeCostReport:
        def execute(self, task_type=None, on_date=None):
            from contest_agent.application.usecases.cost_report import CostSummary, TaskCost

            total = TaskCost(calls=2, prompt_tokens=3000, completion_tokens=800, cost_yuan=0.0184)
            return CostSummary(
                total=total,
                by_task={"identify": TaskCost(calls=2, prompt_tokens=3000,
                                              completion_tokens=800, cost_yuan=0.0184)},
                by_model={"deepseek-chat": total},
            )

    monkeypatch.setattr(
        composition_module, "build_cost_report_usecase", lambda: FakeCostReport()
    )
    exit_code = cli_module.main(["cost", "--task", "identify"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "任务 = identify" in output
    assert "2 次调用" in output
    assert "¥0.0184" in output
    assert "deepseek-chat" in output


def test_sai_cost_empty_ledger(monkeypatch, capsys) -> None:
    """台账为空时给人话提示，而不是打印一排零。"""
    import contest_agent.composition as composition_module
    import contest_agent.presentation.cli as cli_module
    from contest_agent.application.usecases.cost_report import CostSummary

    class FakeCostReport:
        def execute(self, task_type=None, on_date=None):
            return CostSummary()

    monkeypatch.setattr(
        composition_module, "build_cost_report_usecase", lambda: FakeCostReport()
    )
    exit_code = cli_module.main(["cost"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "还没有任何 LLM 调用记录" in output
