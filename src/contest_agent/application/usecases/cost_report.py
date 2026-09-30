"""cost_report 用例：把 usage 流水账汇总成人能读的账单（M1）。

回答的是 v2 规划里的那道验收题："识别 10 条通知花了多少钱？"
数据流：usage_records 表（流水） -> 本用例（按任务/模型分组求和）
-> CLI 或 HTTP 接口（呈现）。

聚合逻辑放用例层而不是 SQL 里，理由和 v1"能复用端口就不扩端口"一致：
仓储只提供"按条件取流水"一个动作，求和分组的规则（比如价格没配的
怎么算、按什么键分组）属于业务，放这里才能用假仓储离线测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ...domain.entities import UsageEntry
from ...domain.ports import UsageRepositoryPort

# 允许按任务过滤的取值（CLI 的 --task 参数照这个校验）
TASK_TYPES = ("identify", "generate", "study_path")


@dataclass
class TaskCost:
    """一个任务维度的花费小计。"""

    calls: int = 0                          # 调用次数
    prompt_tokens: int = 0                  # 输入 token 合计
    completion_tokens: int = 0              # 输出 token 合计
    cost_yuan: float | None = None          # 费用合计（元）；有没配单价的流水时为 None
    _has_unpriced: bool = field(default=False, repr=False)
    # 内部标记：这组里有没有"记了 token 但算不出钱"的流水（单价没配）。
    # 有 → cost_yuan 置 None，呈现层显示"部分未知"，绝不假装算得清


@dataclass
class CostSummary:
    """一次账单查询的汇总结果。"""

    total: TaskCost = field(default_factory=TaskCost)
    by_task: dict[str, TaskCost] = field(default_factory=dict)  # 任务名 -> 小计
    by_model: dict[str, TaskCost] = field(default_factory=dict)  # 模型名 -> 小计


class CostReport:
    """查询并汇总成本台账。"""

    def __init__(self, usage_repository: UsageRepositoryPort):
        # 依赖注入：仓储从外面递进来（装配根纪律），测试时传假仓储
        self.usage_repository = usage_repository

    def execute(
        self,
        task_type: str | None = None,
        on_date: date | None = None,
    ) -> CostSummary:
        """按条件取流水并汇总。task_type / on_date 都是可选过滤器。"""
        entries = self.usage_repository.list_entries(
            task_type=task_type, on_date=on_date
        )

        summary = CostSummary()
        for entry in entries:
            summary.total = _accumulate(summary.total, entry)
            summary.by_task[entry.task_type] = _accumulate(
                summary.by_task.get(entry.task_type, TaskCost()), entry
            )
            summary.by_model[entry.model] = _accumulate(
                summary.by_model.get(entry.model, TaskCost()), entry
            )
        return summary


def _accumulate(bucket: TaskCost, entry: UsageEntry) -> TaskCost:
    """把一条流水累进小计桶（纯函数：返回新桶，不改旧桶）。"""
    bucket.calls += 1
    bucket.prompt_tokens += entry.prompt_tokens
    bucket.completion_tokens += entry.completion_tokens
    if entry.cost_yuan is None:
        # 只要有一笔算不出钱，整组费用就只能标"未知"——宁可显示缺失
        # 也不给个假总数（这是账本的诚实原则）。_has_unpriced 记住这个状态，
        # 后面再遇到有钱的流水也不能"恢复"出总数
        bucket._has_unpriced = True
        bucket.cost_yuan = None
    elif not bucket._has_unpriced:
        bucket.cost_yuan = (bucket.cost_yuan or 0.0) + entry.cost_yuan
    return bucket
