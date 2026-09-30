"""FastAPI 呈现层：把 HTTP 请求翻译成对用例的调用（P6 全量接口）。

呈现层纪律：这里只做三件事——解析请求、调用用例、组装响应。
所有业务逻辑都在 application 层的用例里。

接口一览：
    GET  /health        健康检查
    POST /scan          扫描官网通知（写台账）
    GET  /competitions  查询已识别的比赛卡片
    GET  /report        获取 Markdown 情报报告
    POST /generate      生成参赛材料（AgentScope 循环，耗时 30-90 秒）
    POST /study-path    生成备考路径（联网搜索 + 引用校验，耗时 40-90 秒）

密钥未配置时的降级策略：需要 LLM 的接口（/generate /study-path）返回 503
并附带配置指引，其余接口照常可用——同学没有密钥也能跑通前半程。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..application.usecases.generate_material import GenerateMaterial
from ..application.usecases.generate_report import GenerateReport
from ..application.usecases.identify_competitions import IdentifyCompetitions
from ..application.usecases.plan_study_path import PlanStudyPath
from ..application.usecases.scan_site import ScanSite
from ..settings import Settings


@dataclass
class Usecases:
    """HTTP 层可调用的全部用例，由装配根一次性注入。

    LLM 相关的用例（identify/generate_material/study_path）在密钥缺失时
    会是 None——对应接口返回 503 和配置指引，而不是整个服务起不来。
    """

    scan: ScanSite | None = None
    identify: IdentifyCompetitions | None = None
    report: GenerateReport | None = None
    generate_material: GenerateMaterial | None = None
    study_path: PlanStudyPath | None = None


# —— 请求体模型（pydantic 自动校验：字段缺失/类型不对会自动返回 422） ——


class ScanRequest(BaseModel):
    limit: int = 10
    detail: int | None = None  # 可选：给第几条通知补抓详情正文


class GenerateRequest(BaseModel):
    skill: str = "ppt-outline"
    competition: str | None = None


class StudyPathRequest(BaseModel):
    competition: str | None = None


def _notice_to_dict(notice) -> dict:
    """Notice 实体 -> 响应字典（日期转成 ISO 字符串）。"""
    return {
        "title": notice.title,
        "url": notice.source_url,
        "published_at": notice.published_at.isoformat() if notice.published_at else None,
        "content": notice.content,
    }


def _card_to_dict(card) -> dict:
    """Competition 实体 -> 响应字典。"""
    return {
        "name": card.name,
        "type": card.type,
        "deadline": card.deadline.isoformat() if card.deadline else None,
        "notice_url": card.notice_url,
        "evidence": card.evidence,
    }


class MarkdownResponse(PlainTextResponse):
    """纯文本响应的变体：Content-Type 标为 text/markdown。"""

    media_type = "text/markdown"


def create_app(settings: Settings | None = None, usecases: Usecases | None = None) -> FastAPI:
    """创建 FastAPI 应用。usecases 由装配根注入；测试时可以传假用例。"""
    app = FastAPI(
        title="contest_agent",
        version="0.1.0",
        description="比赛 Agent 助手 API",
    )

    @app.get("/health")
    def health() -> dict:
        """健康检查：监控/网关定期来戳一下，确认服务活着。"""
        payload: dict = {"status": "ok", "version": "0.1.0"}
        if settings is not None:
            payload["active_model"] = settings.active_model
        return payload

    @app.post("/scan")
    def scan(req: ScanRequest) -> dict:
        """扫描官网通知（幂等写台账），返回最新通知列表。"""
        if usecases is None or usecases.scan is None:
            raise HTTPException(503, "扫描功能未装配")
        try:
            notices = usecases.scan.execute(
                limit=req.limit,
                detail_indexes=[req.detail] if req.detail is not None else None,
            )
        except ConnectionError as error:
            raise HTTPException(502, f"抓取失败：{error}")
        return {
            "count": len(notices),
            "sync": usecases.scan.last_sync,
            "notices": [_notice_to_dict(n) for n in notices],
        }

    @app.get("/competitions")
    def competitions() -> dict:
        """查询已识别的全部比赛卡片。"""
        if usecases is None or usecases.report is None:
            raise HTTPException(503, "查询功能未装配")
        cards = usecases.report.repository.list_all()
        return {"count": len(cards), "competitions": [_card_to_dict(c) for c in cards]}

    @app.get("/report", response_class=MarkdownResponse)
    def report() -> str:
        """获取 Markdown 格式的比赛情报报告。"""
        if usecases is None or usecases.report is None:
            raise HTTPException(503, "报告功能未装配")
        return usecases.report.execute()

    @app.post("/generate")
    def generate(req: GenerateRequest) -> dict:
        """为比赛生成参赛材料（AgentScope 循环驱动，可能耗时 30-90 秒）。"""
        if usecases is None or usecases.generate_material is None:
            raise HTTPException(
                503, "材料生成需要 LLM 密钥：请在 .env 里配置 DEEPSEEK_API_KEY"
            )
        try:
            result = usecases.generate_material.execute(
                skill_name=req.skill, competition_name=req.competition
            )
        except FileNotFoundError as error:
            raise HTTPException(404, str(error))
        except RuntimeError as error:
            raise HTTPException(400, str(error))
        except ConnectionError as error:
            raise HTTPException(502, str(error))
        return {
            "success": result.success,
            "competition": result.competition_name,
            "skill": result.skill_name,
            "tool_trace": result.tool_trace,
            "final_text": result.final_text,
        }

    @app.post("/study-path")
    def study_path(req: StudyPathRequest) -> dict:
        """生成备考路径并校验全部引用（联网搜索，可能耗时 40-90 秒）。"""
        if usecases is None or usecases.study_path is None:
            raise HTTPException(
                503, "备考路径需要 LLM 密钥：请在 .env 里配置 DEEPSEEK_API_KEY"
            )
        try:
            result = usecases.study_path.execute(competition_name=req.competition)
        except FileNotFoundError as error:
            raise HTTPException(404, str(error))
        except RuntimeError as error:
            raise HTTPException(400, str(error))
        except ConnectionError as error:
            raise HTTPException(502, str(error))
        return {
            "success": result.success,
            "competition": result.competition_name,
            "citations": result.citations,
            "tool_trace": result.tool_trace,
            "final_text": result.final_text,
        }

    return app
