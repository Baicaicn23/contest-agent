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
)
from .infrastructure.search.web_search import BingSearch
from .presentation.server import Usecases, create_app
from .settings import PROJECT_ROOT, Settings, load_settings

__all__ = [
    "app",
    "build_app",
    "build_competition_repository",
    "build_generate_material_usecase",
    "build_identify_usecase",
    "build_llm",
    "build_notice_repository",
    "build_notice_source",
    "build_plan_study_path_usecase",
    "build_report_usecase",
    "build_scan_usecase",
    "build_search",
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


def build_llm() -> OpenAiCompatLlm:
    """组装 LLM 客户端：按当前生效的模型档案创建（P2）。

    密钥缺失会在这里立刻报错（而不是等到调用时），错误信息里
    会指明该设置哪个环境变量。
    """
    settings = load_settings_or_raise()
    return OpenAiCompatLlm(settings.active_profile)


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
        build_notice_source(), build_llm(), build_competition_repository()
    )


def build_report_usecase() -> GenerateReport:
    """组装 generate_report 用例：从卡片仓储读数据渲染 Markdown 报告（P3）。"""
    return GenerateReport(build_competition_repository())


def build_generate_material_usecase(output_dir: Path | None = None) -> GenerateMaterial:
    """组装 generate_material 用例（P4，循环由 AgentScope 驱动）。

    output_dir 默认项目根的 output/；测试时传临时目录。
    """
    settings = load_settings_or_raise()
    return GenerateMaterial(
        profile=settings.active_profile,
        source=build_notice_source(),
        competition_repository=build_competition_repository(),
        output_dir=output_dir or (PROJECT_ROOT / "output"),
    )


def build_search() -> BingSearch:
    """组装联网搜索：Bing 中国版 + 360 回退（P5，无需密钥）。"""
    settings = load_settings_or_raise()
    return BingSearch(settings.yaml_config.search)


def build_plan_study_path_usecase(output_dir: Path | None = None) -> PlanStudyPath:
    """组装 plan_study_path 用例：模型档案 + 搜索 + 卡片仓储（P5）。"""
    settings = load_settings_or_raise()
    return PlanStudyPath(
        profile=settings.active_profile,
        search=build_search(),
        competition_repository=build_competition_repository(),
        output_dir=output_dir or (PROJECT_ROOT / "output"),
    )


def build_usecases() -> Usecases:
    """组装 HTTP 层可用的全部用例（P6）。

    降级策略：LLM 相关的用例（识别/生成/备考路径）依赖密钥，
    密钥没配时它们保持 None（对应接口返回 503 + 配置指引），
    其余接口（扫描/查询/报告）照常可用——同学没密钥也能跑通前半程。
    """
    settings = load_settings_or_raise()

    try:
        llm = build_llm()
    except RuntimeError:
        # 密钥缺失：不让整个服务起不来，只降级 LLM 相关接口
        llm = None

    return Usecases(
        scan=ScanSite(build_notice_source(), build_notice_repository()),
        identify=(
            IdentifyCompetitions(build_notice_source(), llm, build_competition_repository())
            if llm is not None
            else None
        ),
        report=GenerateReport(build_competition_repository()),
        generate_material=(
            GenerateMaterial(
                profile=settings.active_profile,
                source=build_notice_source(),
                competition_repository=build_competition_repository(),
                output_dir=PROJECT_ROOT / "output",
            )
            if llm is not None
            else None
        ),
        study_path=(
            PlanStudyPath(
                profile=settings.active_profile,
                search=build_search(),
                competition_repository=build_competition_repository(),
                output_dir=PROJECT_ROOT / "output",
            )
            if llm is not None
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
