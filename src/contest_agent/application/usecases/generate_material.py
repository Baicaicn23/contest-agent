"""generate_material 用例：为比赛生成参赛材料（AgentScope 驱动，v1.5）。

和 P2 的识别（单次结构化调用）不同，材料生成需要模型多轮决策：
查比赛 -> 读通知原文 -> 构思 -> 落盘 -> 汇报。循环本体由 AgentScope
的 Agent 驱动（ADR-002），本用例负责的是"业务编排"这一层：
选卡、装提示词（基础守则 + 技能指令）、点火、打包结果。

框架的组装细节全部在 harness/agent_factory.py，
本文件通过注入 runner 的方式与之解耦——测试时塞假 runner，不碰真框架。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ...domain.entities import Competition
from ...domain.ports import CompetitionRepositoryPort, NoticeSourcePort
from ...settings import ModelProfile
from ..harness.agent_factory import (
    AgentOutcome,
    MaterialTools,
    build_material_tools,
    run_material_generation,
)
from ..harness.skills import Skill, load_skill

# 基础人设与工作守则：无论什么技能，agent 都要守的规矩。
# 技能文件（skills/*.md）负责"这次具体怎么干"，这里只负责"永远怎么干"。
BASE_AGENT_PROMPT = """\
你是"比赛 Agent 助手"，负责为大学生准备比赛参赛材料。

工作守则：
1. 先查证再动笔：写材料前，先用工具了解比赛信息和通知原文，不要凭空编造赛程和要求；
2. 材料必须通过 save_material 保存为 .md 文件，保存后把文件名明确告诉用户；
3. 工具报错时，读一下错误信息、修正参数重试，不要直接放弃；
4. 任务完成后，用一段话向用户总结：你做了什么、生成了哪个文件、建议用户接下来检查什么。
"""

# 生产环境的 runner：AgentScope 接驳层的同步门面
DefaultRunner = Callable[..., tuple[AgentOutcome, MaterialTools]]


@dataclass
class MaterialResult:
    """一次材料生成的结果。"""

    final_text: str       # 模型的收尾总结
    success: bool         # True=正常结束；False=框架报告了错误
    skill_name: str
    competition_name: str
    error: str | None = None
    tool_trace: list[str] = field(default_factory=list)
    # 每步的工具调用轨迹（人话格式），给 CLI 播报用——
    # 材料是模型生成的，人必须能看到它查了什么、写了什么才敢用
    pptx_file: str | None = None  # M4 收尾：导出的 .pptx 文件名（仅 ppt-outline 技能；None=未导出）
    pptx_hint: str | None = None  # M4 收尾：pptx 导出失败时的降级提示（任务本身仍算成功）


class GenerateMaterial:
    """为某场比赛按某个技能生成材料（循环由 AgentScope 驱动）。"""

    def __init__(
        self,
        profile: ModelProfile,
        source: NoticeSourcePort,
        competition_repository: CompetitionRepositoryPort,
        output_dir: Path,
        max_iters: int = 8,
        runner: DefaultRunner | None = None,
        meter=None,
        context_config=None,
        recorder=None,
        gate=None,
        exporter=None,
    ):
        self.profile = profile
        self.source = source
        self.competition_repository = competition_repository
        self.output_dir = output_dir
        self.max_iters = max_iters
        # runner 可注入：生产用 AgentScope 门面，测试用假 runner
        self.runner: DefaultRunner = runner or run_material_generation
        # M1/M2/M3 可选注入：计价器、压缩配置、会话记录器、权限门。
        # 类型标注从简：各类型分属应用层与框架，这里只做搬运工
        self.meter = meter
        self.context_config = context_config
        self.recorder = recorder
        self.gate = gate
        # M4 收尾：幻灯片导出器（infra 的 SlidesExporter，鸭子类型不标类型）。
        # 只在 ppt-outline 技能成功后调用；None = 不导出
        self.exporter = exporter

    def execute(
        self, skill_name: str, competition_name: str | None = None
    ) -> MaterialResult:
        """执行生成。competition_name 不给就取库里截止日期最近的一张卡。

        M2 起全程写会话事件：无论成败，sai replay 都能回放这次任务。
        """
        try:
            result = self._execute_inner(skill_name, competition_name)
        except Exception as error:
            if self.recorder is not None:
                self.recorder.log("error", error=str(error))
                self.recorder.finish("failed")
            raise
        if self.recorder is not None:
            if result.success:
                self.recorder.finish("completed")
            elif result.error and "预算熔断" in result.error:
                self.recorder.finish("budget_break")
            else:
                self.recorder.finish("failed")
        return result

    def _execute_inner(
        self, skill_name: str, competition_name: str | None = None
    ) -> MaterialResult:
        """真正的生成流程（execute 只负责会话状态盖章这一层壳）。"""
        skill = load_skill(skill_name)
        card = self._pick_card(competition_name)

        deadline = card.deadline.strftime("%Y-%m-%d") if card.deadline else "通知内未写"
        system_prompt = self._compose_system_prompt(skill)
        user_request = (
            f"请为比赛「{card.name}」生成材料。\n"
            f"技能：{skill.name}（{skill.description}）\n"
            f"比赛卡片：类型={card.type}，截止={deadline}，来源通知={card.notice_url}"
        )

        async def tools_builder() -> MaterialTools:
            return await build_material_tools(
                source=self.source,
                competition_repository=self.competition_repository,
                output_dir=self.output_dir,
                recorder=self.recorder,
                gate=self.gate,
            )

        outcome, tools = self.runner(
            profile=self.profile,
            system_prompt=system_prompt,
            user_request=user_request,
            tools_builder=tools_builder,
            max_iters=self.max_iters,
            meter=self.meter,
            context_config=self.context_config,
            recorder=self.recorder,
        )

        result = MaterialResult(
            final_text=outcome.final_text,
            success=outcome.error is None,
            skill_name=skill.name,
            competition_name=card.name,
            error=outcome.error,
            tool_trace=list(tools.trace),
        )

        # M4 收尾：ppt-outline 成功后把大纲导出成 .pptx。
        # 降级原则：大纲 .md 已经在手，pptx 失败只记提示、不毁任务
        if self.exporter is not None and result.success and skill_name == "ppt-outline":
            markdown_file = self.output_dir / "ppt-outline.md"
            if markdown_file.exists():
                try:
                    info = self.exporter.export(
                        markdown_file.read_text(encoding="utf-8"),
                        self.output_dir / "ppt-outline.pptx",
                    )
                    result.pptx_file = info["path"].name
                except Exception as export_error:
                    result.pptx_hint = f"pptx 导出失败：{export_error}"

        return result

    # ---------- 内部步骤 ----------

    def _pick_card(self, name: str | None) -> Competition:
        """选目标比赛：按名称模糊匹配；不指定就取第一张（截止最近的）。"""
        cards = self.competition_repository.list_all()
        if not cards:
            raise RuntimeError("库里还没有比赛卡片，请先运行 sai identify 识别比赛。")
        if name is None:
            return cards[0]
        for card in cards:
            if name in card.name:
                return card
        available = "、".join(c.name for c in cards)
        raise RuntimeError(f"没找到名称包含 {name!r} 的比赛。库里现有：{available}")

    def _compose_system_prompt(self, skill: Skill) -> str:
        """系统提示词 = 基础守则 + 本次技能指令，两段拼接。"""
        return f"{BASE_AGENT_PROMPT}\n\n# 本次任务的技能指令\n\n{skill.instructions}"
