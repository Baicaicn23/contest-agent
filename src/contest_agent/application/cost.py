"""成本计量器（CostMeter）：每次 LLM 任务的"计价器 + 预算闸"（M1）。

它解决两个问题：
1. 记账：每次调用 LLM 后，把 token 量和折算费用写进 usage_records 台账，
   让"sai cost"能回答"这个任务花了多少钱"；
2. 熔断：任务开始前配置一个预算上限（元），花超了立刻抛
   BudgetExceededError 把任务拦下来——而不是等账单来了才发现失控。

为什么放在 application 层？——"怎么算钱、超没超预算"是业务规则，
不是某个技术组件的私事；它只依赖 UsageRepositoryPort（接口）和
ModelProfile（配置对象），不碰任何框架。类比后端：这是一个
@Service 的领域服务，谁调 LLM 谁带上它。

费用怎么算？——费用 = 输入token/1M × 输入单价 + 输出token/1M × 输出单价。
单价写在 config.yaml 的模型档案里（元/百万 token，照服务商价目页填），
调价时改配置即可，代码不动。注意：单价是"当时填的"，账单翻旧账时
若中途调过价会有误差——真要精确审计得存"成交价快照"，v2 先不做（见 ADR-003）。
"""

from __future__ import annotations

from ..settings import ModelProfile
from ..domain.entities import UsageEntry
from ..domain.ports import UsageRepositoryPort


class BudgetExceededError(RuntimeError):
    """任务花费超出预算上限时抛出。

    继承 RuntimeError 是有意的：CLI 和 FastAPI 的现有异常处理
    （except RuntimeError）不用改就能兜住它。
    """

    pass


def compute_cost_yuan(
    prompt_tokens: int,
    completion_tokens: int,
    input_price_per_m: float | None,
    output_price_per_m: float | None,
) -> float | None:
    """按"单价 × 用量"折算本次调用费用（元）；任一单价没配就返回 None。

    单独抽成函数：算钱规则集中一处，将来要支持"按次计费""缓存折扣"
    等花活，只改这里。
    """
    if input_price_per_m is None or output_price_per_m is None:
        return None
    input_cost = prompt_tokens / 1_000_000 * input_price_per_m
    output_cost = completion_tokens / 1_000_000 * output_price_per_m
    return input_cost + output_cost


class CostMeter:
    """一次任务的计价器：记录每次 LLM 调用，花费超预算就熔断。

    生命周期 = 一次任务（一次 sai identify / sai generate 命令，
    或一次 HTTP 调用）。由装配根创建并塞给 LLM 客户端，用例层
    完全无感——这是刻意的：记账和熔断是横切关注点（cross-cutting
    concern），让每个用例自己记账，迟早有人忘记。
    """

    def __init__(
        self,
        profile: ModelProfile,
        task_type: str,
        repository: UsageRepositoryPort | None = None,
        budget_yuan: float | None = None,
        note: str = "",
    ):
        self.profile = profile
        self.task_type = task_type
        # repository 允许为 None（比如纯内存测试不想建库）：照常熔断，只是不落账
        self.repository = repository
        # budget_yuan None = 不限预算；配了就逐笔累计、超线熔断
        self.budget_yuan = budget_yuan
        self.note = note

        self.spent_yuan: float = 0.0   # 本任务已累计花费（元）
        self.call_count: int = 0       # 本任务已调用次数

    def precheck(self) -> None:
        """发起 LLM 调用前检查：预算已花满就拦下，一次多余的钱都不花。

        为什么在调用"前"而不是"后"才拦？——后拦只是事后报警，
        前拦才是熔断：上一个调用把预算花满了，下一个调用根本不该发出去。
        """
        if self.budget_yuan is None:
            return
        if self.spent_yuan >= self.budget_yuan:
            raise BudgetExceededError(
                f"预算熔断：任务 {self.task_type!r} 已花费 "
                f"{self.spent_yuan:.4f} 元，达到上限 {self.budget_yuan} 元，"
                f"剩余调用被拦下（已产生的调用和入库结果不受影响）。"
            )

    def record(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        """记一笔调用流水（token 数来自服务商响应），返回本次费用。

        只记账、不拦截——拦截统一由 precheck 在"下一次调用发出前"做。
        原因：走到 record 这一步，钱已经花了、响应也已经拿到了，
        此时抛异常等于把到手的成果扔掉；熔断的正确姿势是
        "这笔记完，下一笔别发"。
        """
        cost = compute_cost_yuan(
            prompt_tokens,
            completion_tokens,
            self.profile.input_price_per_m,
            self.profile.output_price_per_m,
        )
        self.call_count += 1
        if cost is not None:
            self.spent_yuan += cost

        if self.repository is not None:
            self.repository.record(
                UsageEntry(
                    task_type=self.task_type,
                    profile_name=self.profile.name,
                    model=self.profile.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_yuan=cost,
                    note=self.note,
                )
            )
        return cost
