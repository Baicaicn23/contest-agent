"""plan_study_path 用例：为考试型比赛生成带真实引用的备考路径（P5）。

这是本项目第一个"生成 → 程序校验 → 反馈重试"的完整闭环：

    1. 选卡（优先考试型）
    2. agent 生成路径（工具：搜索 / 读网页 / 落盘 / 查卡片）
    3. 程序从材料里提取全部网址，逐一验证是否存在（引用存在性校验）
    4. 有死链 → 把死链清单反馈给 agent 重做（最多 MAX_VERIFY_ROUNDS 轮）

设计立场：技能文件里"只引用搜索结果里的网址"是**软约束**（靠模型自觉），
本用例的网址验证是**硬约束**（靠程序）——防幻觉最终靠的是程序，不是模型的自觉。
这也是"引用存在性校验"在 P2 原文证据思路上的升级：从"摘原文"到"链接必须真的能打开"。
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ...domain.entities import Competition
from ...domain.ports import CompetitionRepositoryPort, SearchPort
from ...settings import ModelProfile
from ..harness.agent_factory import (
    AgentOutcome,
    MaterialTools,
    build_study_tools,
    run_material_generation,
)
from ..harness.skills import load_skill
from .generate_material import BASE_AGENT_PROMPT

# 校验-反馈的最大轮数：1 轮生成 + 最多 1 轮修正。再多就是提示词有问题，该回去改技能文件
MAX_VERIFY_ROUNDS = 2
# 技能文件约定的材料文件名（校验时按它找文件）
MATERIAL_FILENAME = "study-path.md"

# 从 Markdown 里提取网址的正则：匹配 http/https 开头、到空白/括号/常见中英文标点为止
# （排除集合里同时包含半角和全角括号引号——中文材料的括号是全角的，漏了会把括号内容带进网址）
URL_PATTERN = re.compile(r"https?://[^\s()\[\]{}<>\"'，。；！？（）【】《》「」]+")


def extract_urls(markdown: str) -> list[str]:
    """从 Markdown 文本里提取全部网址（去重、去尾部标点、保持出现顺序）。"""
    seen: set[str] = set()
    urls: list[str] = []
    for raw in URL_PATTERN.findall(markdown):
        url = raw.rstrip(".,;：:、")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


@dataclass
class StudyPathResult:
    """一次备考路径生成的结果。"""

    final_text: str            # 模型的收尾总结
    success: bool              # 全部链接验证通过（且无框架错误）才算成功
    error: str | None = None
    competition_name: str = ""
    material_file: str = MATERIAL_FILENAME
    citations: list[dict] = field(default_factory=list)  # [{url, ok, note}]
    tool_trace: list[str] = field(default_factory=list)


class PlanStudyPath:
    """生成备考学习路径，并对全部引用做存在性校验。"""

    def __init__(
        self,
        profile: ModelProfile,
        search: SearchPort,
        competition_repository: CompetitionRepositoryPort,
        output_dir: Path,
        max_iters: int = 14,
        max_verify_rounds: int = MAX_VERIFY_ROUNDS,
        runner: Callable | None = None,
        meter=None,
        context_config=None,
        recorder=None,
        digest_llm=None,
        gate=None,
    ):
        self.profile = profile
        self.search = search
        self.competition_repository = competition_repository
        self.output_dir = output_dir
        self.max_iters = max_iters
        self.max_verify_rounds = max_verify_rounds
        # runner 可注入：生产用 AgentScope 门面，测试用假 runner
        self.runner = runner or run_material_generation
        # M1/M2/M3 可选注入：计价器、压缩配置、会话记录器、研究分身 LLM、权限门
        self.meter = meter
        self.context_config = context_config
        self.recorder = recorder
        self.digest_llm = digest_llm
        self.gate = gate

    def execute(self, competition_name: str | None = None) -> StudyPathResult:
        """生成备考路径并校验引用；有死链自动反馈重做一轮。

        M2 起全程写会话事件（多轮校验的每一轮都在轨迹里），结束时按
        结局盖状态戳：completed / failed / budget_break。
        """
        try:
            result = self._execute_inner(competition_name)
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

    def _execute_inner(self, competition_name: str | None = None) -> StudyPathResult:
        """真正的生成-校验循环（execute 只负责会话状态盖章这一层壳）。"""
        skill = load_skill("study-path")
        card = self._pick_card(competition_name)

        system_prompt = f"{BASE_AGENT_PROMPT}\n\n# 本次任务的技能指令\n\n{skill.instructions}"
        deadline = card.deadline.strftime("%Y-%m-%d") if card.deadline else "通知内未写"
        base_request = (
            f"请为比赛「{card.name}」制定备考学习路径。\n"
            f"比赛卡片：类型={card.type}，报名/考试时间={deadline}，来源通知={card.notice_url}\n"
            f"材料保存文件名必须是：{MATERIAL_FILENAME}"
        )

        checks: list[dict] = []
        outcome = AgentOutcome(final_text="", error=None)
        tool_trace: list[str] = []

        for round_number in range(1, self.max_verify_rounds + 1):
            # 第 2 轮起，把上一轮的死链清单作为反馈追加进请求
            request = base_request
            dead = [c for c in checks if not c["ok"]]
            if round_number > 1 and dead:
                dead_list = "\n".join(f"- {c['url']}（{c['note']}）" for c in dead)
                request = (
                    f"{base_request}\n\n"
                    f"注意：上一版材料里以下链接经验证失效，必须替换或删除后重新保存材料：\n{dead_list}"
                )

            async def tools_builder() -> MaterialTools:
                return await build_study_tools(
                    search=self.search,
                    competition_repository=self.competition_repository,
                    output_dir=self.output_dir,
                    recorder=self.recorder,
                    digest_llm=self.digest_llm,
                    gate=self.gate,
                )

            outcome, tools = self.runner(
                profile=self.profile,
                system_prompt=system_prompt,
                user_request=request,
                tools_builder=tools_builder,
                max_iters=self.max_iters,
                meter=self.meter,
                context_config=self.context_config,
                recorder=self.recorder,
            )
            tool_trace = list(tools.trace)

            # 框架层出错（网络/密钥等）：没有可校验的材料，直接失败返回
            if outcome.error:
                return self._result(outcome, card, checks, tool_trace, error=outcome.error)

            # 引用存在性校验：从材料文件提取网址，逐一验证
            material_file = self.output_dir / MATERIAL_FILENAME
            if not material_file.exists():
                return self._result(
                    outcome, card, checks, tool_trace,
                    error=f"agent 没有保存材料文件 {MATERIAL_FILENAME}",
                )
            urls = extract_urls(material_file.read_text(encoding="utf-8"))
            checks = self._verify(urls)

            if urls and all(c["ok"] for c in checks):
                break  # 全部链接真实存在：任务完成

        success = outcome.error is None and bool(checks) and all(c["ok"] for c in checks)
        return self._result(outcome, card, checks, tool_trace, success=success)

    # ---------- 内部步骤 ----------

    def _pick_card(self, name: str | None) -> Competition:
        """选目标比赛：优先考试型；指定名称则模糊匹配；库里为空则报错。"""
        cards = self.competition_repository.list_all()
        if not cards:
            raise RuntimeError("库里还没有比赛卡片，请先运行 sai identify 识别比赛。")

        if name is not None:
            for card in cards:
                if name in card.name:
                    return card
            available = "、".join(c.name for c in cards)
            raise RuntimeError(f"没找到名称包含 {name!r} 的比赛。库里现有：{available}")

        # 不指定名称：优先挑考试型（备考路径的主场景），否则取第一张
        for card in cards:
            if card.type == "exam":
                return card
        return cards[0]

    def _verify(self, urls: list[str]) -> list[dict]:
        """并行验证全部网址（一个网址一次 HTTP，串行太慢）。"""
        if not urls:
            return []
        with ThreadPoolExecutor(max_workers=min(len(urls), 8)) as pool:
            results = list(
                pool.map(lambda url: (url, *self.search.check_url(url)), urls)
            )
        return [{"url": url, "ok": ok, "note": note} for url, ok, note in results]

    def _result(
        self,
        outcome: AgentOutcome,
        card: Competition,
        checks: list[dict],
        tool_trace: list[str],
        error: str | None = None,
        success: bool = False,
    ) -> StudyPathResult:
        """统一打包结果：全部链接验证通过（且有链接）才算成功。"""
        return StudyPathResult(
            final_text=outcome.final_text,
            success=success and error is None,
            error=error,
            competition_name=card.name,
            material_file=MATERIAL_FILENAME,
            citations=checks,
            tool_trace=tool_trace,
        )
