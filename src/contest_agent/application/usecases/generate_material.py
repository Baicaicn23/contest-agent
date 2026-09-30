"""generate_material 用例：手写 harness 的第一个业务动作（P4）。

和 P2 的识别（单次结构化调用）不同，材料生成需要模型多轮决策：
查比赛 -> 读通知原文 -> 构思 -> 落盘 -> 汇报。所以这里动用的才是
P4 建的 ReAct 循环（AgentRunner），而不是一问一答。

用例本身的职责很薄：选卡、装提示词（基础人设 + 技能指令）、
组工具箱、点火循环、把结果打包。真正的"干活"在 harness 里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ...domain.entities import Competition
from ...domain.ports import CompetitionRepositoryPort, LlmPort, NoticeSourcePort
from ..harness.loop import AgentRunner
from ..harness.registry import ToolRegistry
from ..harness.skills import Skill, load_skill
from ..tools.material_tools import build_material_tools

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


@dataclass
class MaterialResult:
    """一次材料生成的结果。"""

    final_text: str       # 模型的收尾总结
    success: bool         # True=自然完成；False=步数耗尽被强制停
    steps: int            # 实际走了几轮
    skill_name: str
    competition_name: str
    tool_trace: list[str] = field(default_factory=list)
    # 每步的工具调用轨迹（人话格式），给 CLI 播报用——
    # 材料是模型生成的，人必须能看到它查了什么、写了什么才敢用


class GenerateMaterial:
    """为某场比赛按某个技能生成材料。"""

    def __init__(
        self,
        llm: LlmPort,
        source: NoticeSourcePort,
        competition_repository: CompetitionRepositoryPort,
        output_dir: Path,
        max_steps: int = 8,
    ):
        self.llm = llm
        self.source = source
        self.competition_repository = competition_repository
        self.output_dir = output_dir
        self.max_steps = max_steps

    def execute(
        self, skill_name: str, competition_name: str | None = None
    ) -> MaterialResult:
        """执行生成。competition_name 不给就取库里截止日期最近的一张卡。"""
        skill = load_skill(skill_name)
        card = self._pick_card(competition_name)

        registry = self._build_registry()
        runner = AgentRunner(
            llm=self.llm,
            registry=registry,
            system_prompt=self._compose_system_prompt(skill),
            max_steps=self.max_steps,
        )

        deadline = card.deadline.strftime("%Y-%m-%d") if card.deadline else "通知内未写"
        user_request = (
            f"请为比赛「{card.name}」生成材料。\n"
            f"技能：{skill.name}（{skill.description}）\n"
            f"比赛卡片：类型={card.type}，截止={deadline}，来源通知={card.notice_url}"
        )

        result = runner.run(user_request)

        # 把循环轨迹转成人话：第几步、调了什么工具、关键参数
        tool_trace = []
        for step in result.steps:
            for call in step.tool_calls:
                args_preview = ", ".join(
                    f"{key}={str(value)[:40]}" for key, value in call["arguments"].items()
                )
                tool_trace.append(f"步骤{step.step}：{call['name']}({args_preview})")

        return MaterialResult(
            final_text=result.final_text,
            success=result.success,
            steps=len(result.steps),
            skill_name=skill.name,
            competition_name=card.name,
            tool_trace=tool_trace,
        )

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

    def _build_registry(self) -> ToolRegistry:
        """组装本任务可用的工具箱。"""
        return build_material_tools(
            source=self.source,
            competition_repository=self.competition_repository,
            output_dir=self.output_dir,
        )
