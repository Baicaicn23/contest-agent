"""装配根（composition root）：把所有"零件"组装成能跑的程序，全项目唯一。

先说为什么需要它：domain 层只声明了"我需要会爬通知的人"（NoticeSourcePort），
但不关心具体是谁。那么总得有个地方把具体对象创建出来、递给需要它的人——
这个"组装"的活，全项目只允许在这里干。

好处：以后换实现（SQLite 换 MySQL、DeepSeek 换 GLM、换爬虫库），
只改这一个文件，其他代码一行不动。

组装方向是单向的（左边创建右边）：
    settings -> 爬虫 -> LLM 工厂 -> 仓储 -> 用例 -> FastAPI 应用

类比：这事在 Java/Spring 里是 Spring 容器自动完成的（依赖注入）。
我们没用框架，就手写这个"容器"——顺便也就能看清容器到底干了什么。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from .application.cost import CostMeter
from .application.usecases.cost_report import CostReport
from .application.usecases.generate_material import GenerateMaterial
from .application.usecases.generate_report import GenerateReport
from .application.usecases.identify_competitions import IdentifyCompetitions
from .application.usecases.plan_study_path import PlanStudyPath
from .application.usecases.scan_site import ScanSite
from .infrastructure.crawler.notice_source import RequestsNoticeSource
from .infrastructure.llm.openai_compat import OpenAiCompatLlm
from .infrastructure.persistence.repository import (
    SqliteCompetitionRepository,
    SqliteNoticeRepository,
    SqliteUsageRepository,
)
from .infrastructure.search.web_search import BingSearch
from .presentation.server import Usecases, create_app
from .settings import PROJECT_ROOT, Settings, load_settings

__all__ = [
    "app",
    "build_app",
    "build_competition_repository",
    "build_cost_meter",
    "build_cost_report_usecase",
    "build_generate_material_usecase",
    "build_identify_usecase",
    "build_llm",
    "build_notice_repository",
    "build_notice_source",
    "build_plan_study_path_usecase",
    "build_report_usecase",
    "build_scan_usecase",
    "build_search",
    "build_usage_repository",
    "build_usecases",
]


def load_settings_or_raise() -> Settings:
    """读配置。单独包一层只是为了让装配代码读起来更顺，没有别的魔法。"""
    return load_settings()


# ---------- 基础设施（domain 端口的具体实现，只在这里露面） ----------


def build_notice_source() -> RequestsNoticeSource:
    """组装爬虫：按配置文件里的第一个站点源创建（P1）。

    目前只有一个源；v2 多校源时，这里会变成"按源名创建"的字典/循环。
    """
    settings = load_settings_or_raise()
    return RequestsNoticeSource(settings.yaml_config.sources[0])


def build_llm(task_type: str = "identify") -> OpenAiCompatLlm:
    """组装 LLM 客户端：按任务路由模型档案，并挂上成本计价器（P2 + M1）。

    路由规则见 settings.profile_for_task：identify 这类高频任务可以
    在 config.yaml 的 routing 里指到便宜档案，generate 指到强档案。
    计价器（CostMeter）在这一层挂上——每次调用自动记账 + 预算熔断，
    用例层完全无感。密钥缺失会在这里立刻报错。
    """
    settings = load_settings_or_raise()
    profile = settings.profile_for_task(task_type)
    meter = build_cost_meter(settings, profile, task_type)
    return OpenAiCompatLlm(profile, meter=meter)


def build_usage_repository() -> SqliteUsageRepository:
    """组装成本台账仓储（M1）：和通知/卡片仓储共用同一个数据库文件。"""
    settings = load_settings_or_raise()
    return SqliteUsageRepository(settings.database_url)


def build_cost_meter(
    settings: Settings,
    profile,
    task_type: str,
    note: str = "",
) -> CostMeter:
    """组装计价器：台账仓储 + 预算上限（来自 config.yaml / 环境变量）。

    单独拎出来的原因：identify（本函数）和 agent 循环（下面的
    generate/study_path 组装）两条通路都要计价器，规则只写一处。
    """
    return CostMeter(
        profile=profile,
        task_type=task_type,
        repository=build_usage_repository(),
        budget_yuan=settings.budget_per_task_yuan,
        note=note,
    )


def build_notice_repository() -> SqliteNoticeRepository:
    """组装通知台账仓储：连接串来自 settings（P3）。

    换数据库 = 换 DATABASE_URL 环境变量，本文件都不用动。
    """
    settings = load_settings_or_raise()
    return SqliteNoticeRepository(settings.database_url)


def build_competition_repository() -> SqliteCompetitionRepository:
    """组装比赛卡片仓储（P3）。"""
    settings = load_settings_or_raise()
    return SqliteCompetitionRepository(settings.database_url)


# ---------- 用例（业务动作 = 若干端口能力的编排） ----------


def build_scan_usecase() -> ScanSite:
    """组装 scan_site 用例：爬虫 + 通知台账（P1 纯扫描，P3 起顺手入库）。"""
    return ScanSite(build_notice_source(), build_notice_repository())


def build_identify_usecase() -> IdentifyCompetitions:
    """组装 identify_competitions 用例：爬虫 + LLM + 卡片仓储（P2/P3）。

    这就是"三个端口在一处会师"：用例只管编排，
    具体实现都由本函数决定。
    """
    return IdentifyCompetitions(
        build_notice_source(), build_llm("identify"), build_competition_repository()
    )


def build_report_usecase() -> GenerateReport:
    """组装 generate_report 用例：从卡片仓储读数据渲染 Markdown 报告（P3）。"""
    return GenerateReport(build_competition_repository())


def build_cost_report_usecase() -> CostReport:
    """组装 cost_report 用例：查成本台账并汇总（M1，不需要 LLM 密钥）。"""
    return CostReport(build_usage_repository())


def _build_context_config():
    """按配置生成 AgentScope 的上下文压缩配置（M1）。

    放在 try 里 import：ContextConfig 是框架的类型，只有真的走到
    agent 循环组装时才需要它（保持"不跑 agent 就不碰框架"的老规矩）。
    """
    from agentscope.agent import ContextConfig

    settings = load_settings_or_raise()
    return ContextConfig(trigger_ratio=settings.yaml_config.context.trigger_ratio)


def build_generate_material_usecase(output_dir: Path | None = None) -> GenerateMaterial:
    """组装 generate_material 用例（P4，循环由 AgentScope 驱动）。

    M1 起附带：按任务路由的模型档案 + 计价器（预算熔断）+ 压缩配置。
    output_dir 默认项目根的 output/；测试时传临时目录。
    """
    settings = load_settings_or_raise()
    profile = settings.profile_for_task("generate")
    return GenerateMaterial(
        profile=profile,
        source=build_notice_source(),
        competition_repository=build_competition_repository(),
        output_dir=output_dir or (PROJECT_ROOT / "output"),
        meter=build_cost_meter(settings, profile, "generate"),
        context_config=_build_context_config(),
    )


def build_search() -> BingSearch:
    """组装联网搜索：Bing 中国版 + 360 回退（P5，无需密钥）。"""
    settings = load_settings_or_raise()
    return BingSearch(settings.yaml_config.search)


def build_plan_study_path_usecase(output_dir: Path | None = None) -> PlanStudyPath:
    """组装 plan_study_path 用例：模型档案 + 搜索 + 卡片仓储（P5 + M1 计价）。"""
    settings = load_settings_or_raise()
    profile = settings.profile_for_task("study_path")
    return PlanStudyPath(
        profile=profile,
        search=build_search(),
        competition_repository=build_competition_repository(),
        output_dir=output_dir or (PROJECT_ROOT / "output"),
        meter=build_cost_meter(settings, profile, "study_path"),
        context_config=_build_context_config(),
    )


def build_usecases() -> Usecases:
    """组装 HTTP 层可用的全部用例（P6 + M1 的 /cost）。

    降级策略（沿 v1）：LLM 相关的用例（识别/生成/备考路径）依赖密钥，
    密钥没配（或 routing 指到不存在的档案）时它们保持 None——对应接口
    返回 503 + 配置指引；其余接口（扫描/查询/报告/账单）照常可用。
    M1 起每个 LLM 用例各自路由档案、各挂各的计价器。
    """
    settings = load_settings_or_raise()

    def routed_profile(task_type: str):
        """按任务取档案；routing 配错档案名时返回 None（降级对应接口）。"""
        try:
            return settings.profile_for_task(task_type)
        except KeyError:
            return None

    def llm_ready(profile) -> bool:
        """密钥配好了这个任务的 LLM 用例才能上线（否则接口 503）。"""
        return profile is not None and profile.resolve_api_key() is not None

    identify_profile = routed_profile("identify")
    generate_profile = routed_profile("generate")
    study_profile = routed_profile("study_path")

    return Usecases(
        scan=ScanSite(build_notice_source(), build_notice_repository()),
        identify=(
            IdentifyCompetitions(
                build_notice_source(),
                OpenAiCompatLlm(
                    identify_profile,
                    meter=build_cost_meter(settings, identify_profile, "identify"),
                ),
                build_competition_repository(),
            )
            if llm_ready(identify_profile)
            else None
        ),
        report=GenerateReport(build_competition_repository()),
        cost_report=build_cost_report_usecase(),
        generate_material=(
            GenerateMaterial(
                profile=generate_profile,
                source=build_notice_source(),
                competition_repository=build_competition_repository(),
                output_dir=PROJECT_ROOT / "output",
                meter=build_cost_meter(settings, generate_profile, "generate"),
                context_config=_build_context_config(),
            )
            if llm_ready(generate_profile)
            else None
        ),
        study_path=(
            PlanStudyPath(
                profile=study_profile,
                search=build_search(),
                competition_repository=build_competition_repository(),
                output_dir=PROJECT_ROOT / "output",
                meter=build_cost_meter(settings, study_profile, "study_path"),
                context_config=_build_context_config(),
            )
            if llm_ready(study_profile)
            else None
        ),
    )


# ---------- HTTP 呈现层 ----------


def build_app() -> FastAPI:
    """组装整个应用，返回配置齐全的 FastAPI 实例。"""
    settings = load_settings_or_raise()
    return create_app(settings, build_usecases())


# 模块级 app：cli.py 里 uvicorn.run("contest_agent.composition:app")
# 按这个字符串来启动服务，找到的就是这个变量
app = build_app()
