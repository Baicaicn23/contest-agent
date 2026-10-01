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
from .application.recorder import TaskRecorder
from .application.usecases.chat_service import ChatService
from .application.usecases.cost_report import CostReport
from .application.usecases.deadline_watch import DeadlineSentinel
from .application.usecases.evaluate_identification import EvaluateIdentification
from .application.usecases.generate_material import GenerateMaterial
from .application.usecases.generate_report import GenerateReport
from .application.usecases.identify_competitions import IdentifyCompetitions
from .application.usecases.memory_report import MemoryReport
from .application.usecases.plan_study_path import PlanStudyPath
from .application.usecases.scan_site import ScanSite
from .application.usecases.session_report import SessionReport
from .application.usecases.usage_report import UsageReport
from .application.usecases.watch_site import WatchSite
from .application.usecases.workspace import WorkspaceService
from .infrastructure.crawler.notice_source import RequestsNoticeSource
from .infrastructure.llm.openai_compat import OpenAiCompatLlm
from .infrastructure.persistence.repository import (
    SqliteCompetitionRepository,
    SqliteMemoryRepository,
    SqliteNoticeRepository,
    SqliteProjectRepository,
    SqliteSessionRepository,
    SqliteUsageRepository,
)
from .infrastructure.push.pushers import build_pushers
from .infrastructure.search.web_search import BingSearch
from .presentation.server import Usecases, create_app
from .settings import PROJECT_ROOT, Settings, load_settings

__all__ = [
    "app",
    "build_app",
    "build_chat_service",
    "build_competition_repository",
    "build_cost_meter",
    "build_cost_report_usecase",
    "build_deadline_sentinel",
    "build_eval_usecase",
    "build_generate_material_usecase",
    "build_identify_usecase",
    "build_llm",
    "build_memory_report_usecase",
    "build_memory_repository",
    "build_notice_repository",
    "build_notice_source",
    "build_permission_gate",
    "build_plan_study_path_usecase",    "build_report_usecase",
    "build_scan_usecase",
    "build_search",
    "build_session_report_usecase",
    "build_task_recorder",
    "build_usage_report_usecase",
    "build_usage_repository",
    "build_usecases",
    "build_workspace_service",
    "build_watch_usecase",
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


def build_memory_repository() -> SqliteMemoryRepository:
    """组装持久记忆仓储（M2）：识别结论缓存存在同一个数据库文件里。"""
    settings = load_settings_or_raise()
    return SqliteMemoryRepository(settings.database_url)


def build_session_repository() -> SqliteSessionRepository:
    """组装会话存档仓储（M2）：任务轨迹存在同一个数据库文件里。"""
    settings = load_settings_or_raise()
    return SqliteSessionRepository(settings.database_url)


def build_task_recorder(task_type: str, note: str = "") -> TaskRecorder:
    """开一个新任务会话并返回记录器（M2）。CLI 每次跑任务时调一次。"""
    return TaskRecorder(build_session_repository(), task_type, note)


def build_permission_gate():
    """组装权限门（M3）：两个名单来自 config.yaml 的 permissions 段。

    interactive 不传 = 自动探测（stdin 连着终端才算有人）。
    """
    from .application.harness.permission_gate import PermissionGate

    settings = load_settings_or_raise()
    perms = settings.yaml_config.permissions
    return PermissionGate(
        confirm_tools=perms.confirm_tools,
        unattended_deny_tools=perms.unattended_deny_tools,
        full_access=perms.access_full,
    )


def build_cost_meter(
    settings: Settings,
    profile,
    task_type: str,
    note: str = "",
    session_id: int | None = None,
) -> CostMeter:
    """组装计价器：台账仓储 + 预算上限（来自 config.yaml / 环境变量）。

    单独拎出来的原因：identify（本函数）和 agent 循环（下面的
    generate/study_path 组装）两条通路都要计价器，规则只写一处。
    session_id 有值时，每笔流水都盖会话章——sai sessions 里才能
    显示"这个任务花了多少钱"。
    """
    return CostMeter(
        profile=profile,
        task_type=task_type,
        repository=build_usage_repository(),
        budget_yuan=settings.budget_per_task_yuan,
        note=note,
        session_id=session_id,
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


def build_identify_usecase(note: str = "") -> IdentifyCompetitions:
    """组装 identify_competitions 用例：爬虫 + LLM + 卡片仓储（P2/P3 + M2 记忆/会话）。

    这就是"三个端口在一处会师"：用例只管编排，具体实现都由本函数决定。
    CLI 每次调用都会开一个新会话（recorder），LLM 花费记在该会话名下，
    判断结论写进持久记忆供下次复用。
    """
    settings = load_settings_or_raise()
    recorder = build_task_recorder("identify", note)
    profile = settings.profile_for_task("identify")
    meter = build_cost_meter(settings, profile, "identify", note,
                             session_id=recorder.session_id)
    llm = OpenAiCompatLlm(profile, meter=meter, recorder=recorder)
    return IdentifyCompetitions(
        build_notice_source(),
        llm,
        build_competition_repository(),
        memory=build_memory_repository(),
        recorder=recorder,
    )


def build_report_usecase() -> GenerateReport:
    """组装 generate_report 用例：从卡片仓储读数据渲染 Markdown 报告（P3）。"""
    return GenerateReport(build_competition_repository())


def build_cost_report_usecase() -> CostReport:
    """组装 cost_report 用例：查成本台账并汇总（M1，不需要 LLM 密钥）。"""
    return CostReport(build_usage_repository())


def build_session_report_usecase() -> SessionReport:
    """组装 session_report 用例：查会话存档（M2，不需要 LLM 密钥）。"""
    return SessionReport(build_session_repository())


def build_usage_report_usecase() -> UsageReport:
    """组装 usage_report 用例：Overview 面板的六统计与热力图聚合（M4）。"""
    return UsageReport(build_usage_repository(), build_session_repository())


def build_chat_service() -> ChatService:
    """组装自由对话服务（M4 差异化改造：聊天区背后是真 agent）。

    agent_runner 是一个闭包：每次对话按会话号现造一套"会话级装备"——
    计价器（费用记到该会话）、识别用例（工具里调，同账）、哨兵（只读）——
    再交给 harness 胶水 run_chat_agent_stream 跑 AgentScope 工具循环。
    密钥缺失在这里立刻报错（调用方据此降级 503）。
    """
    from .application.harness.agent_factory import (
        build_chat_tools,
        run_chat_agent_stream,
    )
    from .infrastructure.llm.openai_compat import OpenAiCompatLlm

    settings = load_settings_or_raise()
    chat_profile = settings.profile_for_task("chat")
    identify_profile = settings.profile_for_task("identify")

    async def agent_runner(session_id: int, system_prompt: str,
                           history: list[dict], user_text: str):
        # 会话级装备（闭包内现造，全部记账到同一个 session_id）
        meter = build_cost_meter(
            settings, chat_profile, "chat", note="自由对话", session_id=session_id
        )
        identify_meter = build_cost_meter(
            settings, identify_profile, "identify", session_id=session_id
        )
        memory = build_memory_repository()
        identify_usecase = IdentifyCompetitions(
            build_notice_source(),
            OpenAiCompatLlm(identify_profile, meter=identify_meter),
            build_competition_repository(),
            memory=memory,
        )
        sentinel = DeadlineSentinel(
            competition_repository=build_competition_repository(),
            memory=memory,
            pushers=[],
        )
        tools = await build_chat_tools(
            source=build_notice_source(),
            notice_repository=build_notice_repository(),
            competition_repository=build_competition_repository(),
            search=build_search(),
            identify_usecase=identify_usecase,
            sentinel=sentinel,
        )
        return run_chat_agent_stream(
            profile=chat_profile,
            meter=meter,
            system_prompt=system_prompt,
            history=history,
            user_text=user_text,
            tools=tools,
        )

    return ChatService(
        archive=build_session_repository(),
        competition_repository=build_competition_repository(),
        usage_repository=build_usage_repository(),
        agent_runner=agent_runner,
        model_name=chat_profile.model,
    )


def build_memory_report_usecase() -> MemoryReport:
    """组装 memory_report 用例：查看/清理持久记忆（M2，不需要 LLM 密钥）。"""
    return MemoryReport(build_memory_repository())


def build_eval_usecase(dataset_path=None) -> EvaluateIdentification:
    """组装 eval 评测用例（M2）：考真 LLM、不碰记忆、不写卡片库。

    考试花费照样进台账（task_type=eval，和日常 identify 分开记账），
    但不开会话——sai sessions 回放的是真实任务，不是模拟考。
    """
    settings = load_settings_or_raise()
    profile = settings.profile_for_task("eval")
    meter = build_cost_meter(settings, profile, "eval", note="识别能力评测")
    llm = OpenAiCompatLlm(profile, meter=meter)
    return EvaluateIdentification(llm=llm, dataset_path=dataset_path, meter=meter)


def build_deadline_sentinel(pushers: list | None = None) -> DeadlineSentinel:
    """组装截止日期守望哨兵（M4 差异化①）：扫描卡片 deadline、四档倒计时警报。

    pushers 不传 = 按 config 启用的通道；API 只读列表场景传空列表。
    """
    settings = load_settings_or_raise()
    return DeadlineSentinel(
        competition_repository=build_competition_repository(),
        memory=build_memory_repository(),
        pushers=(
            build_pushers(settings.yaml_config.push) if pushers is None else pushers
        ),
    )


def build_watch_usecase(note: str = "") -> WatchSite:
    """组装 watch 用例（M3 定时推送）：识别 + 所有已启用的推送通道。

    识别部分和 sai identify 完全同款（路由 + 计价 + 记忆 + 会话），
    所以定时跑的每次盯梢同样便宜、同样有轨迹可回放。
    推送通道按 config.yaml 的 push 段装配，一个都没配 = 只识别不外推。
    """
    settings = load_settings_or_raise()
    recorder = build_task_recorder("watch", note)
    profile = settings.profile_for_task("identify")
    meter = build_cost_meter(settings, profile, "identify", note,
                             session_id=recorder.session_id)
    llm = OpenAiCompatLlm(profile, meter=meter, recorder=recorder)
    identify = IdentifyCompetitions(
        build_notice_source(),
        llm,
        build_competition_repository(),
        memory=build_memory_repository(),
        recorder=recorder,
    )
    return WatchSite(identify=identify, pushers=build_pushers(settings.yaml_config.push))


def _build_context_config():
    """按配置生成 AgentScope 的上下文压缩配置（M1）。

    放在 try 里 import：ContextConfig 是框架的类型，只有真的走到
    agent 循环组装时才需要它（保持"不跑 agent 就不碰框架"的老规矩）。
    """
    from agentscope.agent import ContextConfig

    settings = load_settings_or_raise()
    return ContextConfig(trigger_ratio=settings.yaml_config.context.trigger_ratio)


def build_slides_exporter(settings, profile, meter):
    """组装幻灯片导出器（M4 收尾）：大纲 Markdown → .pptx。

    转换用的 LLM 与 generate 主循环共用同一个计价器——导出这次
    结构化调用的花费记在同一本账。
    """
    from .infrastructure.llm.openai_compat import OpenAiCompatLlm
    from .infrastructure.slides.exporter import SlidesExporter

    return SlidesExporter(OpenAiCompatLlm(profile, meter=meter))


def build_generate_material_usecase(output_dir: Path | None = None, note: str = "") -> GenerateMaterial:
    """组装 generate_material 用例（P4，循环由 AgentScope 驱动）。

    M1 起附带：按任务路由的模型档案 + 计价器（预算熔断）+ 压缩配置。
    M2 起附带：会话记录器（CLI 路径每次开新会话，轨迹可回放）。
    output_dir 默认项目根的 output/；测试时传临时目录。
    """
    settings = load_settings_or_raise()
    profile = settings.profile_for_task("generate")
    recorder = build_task_recorder("generate", note)
    meter = build_cost_meter(settings, profile, "generate", note,
                             session_id=recorder.session_id)
    return GenerateMaterial(
        profile=profile,
        source=build_notice_source(),
        competition_repository=build_competition_repository(),
        output_dir=output_dir or (PROJECT_ROOT / "output"),
        meter=meter,
        context_config=_build_context_config(),
        recorder=recorder,
        gate=build_permission_gate(),
        exporter=build_slides_exporter(settings, profile, meter),
    )


def build_search() -> BingSearch:
    """组装联网搜索：Bing 中国版 + 360 回退（P5，无需密钥）。"""
    settings = load_settings_or_raise()
    return BingSearch(settings.yaml_config.search)


def build_plan_study_path_usecase(output_dir: Path | None = None, note: str = "") -> PlanStudyPath:
    """组装 plan_study_path 用例：模型档案 + 搜索 + 卡片仓储（P5 + M1 计价 + M2 会话 + M3 研究分身）。

    digest_llm（研究分身的 LLM 客户端）与主循环共用同一个计价器和会话
    记录器——分身调用的花费记在同一本账、同一份轨迹里，不会另立山头。
    """
    settings = load_settings_or_raise()
    profile = settings.profile_for_task("study_path")
    recorder = build_task_recorder("study_path", note)
    meter = build_cost_meter(settings, profile, "study_path", note,
                             session_id=recorder.session_id)
    digest_llm = OpenAiCompatLlm(profile, meter=meter, recorder=recorder)
    return PlanStudyPath(
        profile=profile,
        search=build_search(),
        competition_repository=build_competition_repository(),
        output_dir=output_dir or (PROJECT_ROOT / "output"),
        meter=meter,
        context_config=_build_context_config(),
        recorder=recorder,
        digest_llm=digest_llm,
        gate=build_permission_gate(),
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

    try:
        chat_service = build_chat_service()
    except RuntimeError:
        chat_service = None  # 密钥缺失：聊天接口降级 503

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
                # HTTP 路径接记忆（结论复用的收益同样成立），但不接会话记录器：
                # 常驻服务在启动时组装用例，若在此开会话，每个进程会永远挂着
                # 一个"running"会话——按请求归档留给后续与 FastAPI 依赖注入一起做
                memory=build_memory_repository(),
            )
            if llm_ready(identify_profile)
            else None
        ),
        report=GenerateReport(build_competition_repository()),
        cost_report=build_cost_report_usecase(),
        sessions=build_session_report_usecase(),
        usage_report=build_usage_report_usecase(),
        chat=chat_service,
        workspace=build_workspace_service(),
        deadline=build_deadline_sentinel(pushers=[]),
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


def build_workspace_service() -> WorkspaceService:
    """组装工作台面板服务（M5）：项目/搜索/通知/技能/文件/git/插件的数据源。

    环境细节以注入方式进来：skills 与 output 是目录 Path，
    git 分支与终端命令用 subprocess 回调——application 层不碰文件系统与子进程。
    """
    import subprocess
    import time

    settings = load_settings_or_raise()

    def git_runner() -> str:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=PROJECT_ROOT,
        )
        return result.stdout

    def command_runner(command: str) -> dict:
        """右侧终端面板的执行回调（M7）。

        安全取舍：本项目是本地单机工具，且界面已有"完全访问"总闸语义——
        终端就是本机用户跑自己的命令，不做白名单；工程上守住三条底线：
        30 秒超时、输出截断到 10KB（防一条命令灌爆响应）、stdout+stderr 合并返回。
        """
        started = time.monotonic()
        try:
            proc = subprocess.run(
                command, shell=True,
                cwd=PROJECT_ROOT,
                capture_output=True, text=True, timeout=30,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            return {
                "command": command,
                "exit_code": proc.returncode,
                "output": output[-10_000:],   # 只留最后 10KB：报错信息通常在尾部
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        except subprocess.TimeoutExpired:
            return {
                "command": command, "exit_code": -1,
                "output": "（超时：命令 30 秒未结束，已终止）",
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        except OSError as error:
            return {
                "command": command, "exit_code": -1,
                "output": f"执行失败：{error}", "duration_ms": 0,
            }

    return WorkspaceService(
        competition_repository=build_competition_repository(),
        session_archive=build_session_repository(),
        notice_repository=build_notice_repository(),
        project_store=SqliteProjectRepository(settings.database_url),
        usage_repository=build_usage_repository(),
        memory=build_memory_repository(),
        skills_dir=PROJECT_ROOT / "skills",
        output_dir=PROJECT_ROOT / "output",
        git_runner=git_runner,
        command_runner=command_runner,
    )


# 模块级 app：cli.py 里 uvicorn.run("contest_agent.composition:app")
# 按这个字符串来启动服务，找到的就是这个变量
app = build_app()

