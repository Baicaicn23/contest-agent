"""FastAPI 呈现层：把 HTTP 请求翻译成对用例的调用（P6 全量接口）。

呈现层纪律：这里只做三件事——解析请求、调用用例、组装响应。
所有业务逻辑都在 application 层的用例里。

接口一览：
    GET  /health        健康检查
    POST /scan          扫描官网通知（写台账）
    GET  /competitions  查询已识别的比赛卡片
    GET  /report        获取 Markdown 情报报告
    GET  /cost          查询 LLM 成本台账（M1）
    GET  /sessions      最近任务会话列表（M2）
    GET  /sessions/{id} 一个会话的完整轨迹回放（M2）
    POST /generate      生成参赛材料（AgentScope 循环，耗时 30-90 秒）
    POST /study-path    生成备考路径（联网搜索 + 引用校验，耗时 40-90 秒）

密钥未配置时的降级策略：需要 LLM 的接口（/generate /study-path）返回 503
并附带配置指引，其余接口照常可用——同学没有密钥也能跑通前半程。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from ..application.usecases.cost_report import TASK_TYPES, CostReport
from ..application.usecases.chat_service import ChatService
from ..application.usecases.generate_material import GenerateMaterial
from ..application.usecases.session_report import SessionReport
from ..application.usecases.generate_report import GenerateReport
from ..application.usecases.identify_competitions import IdentifyCompetitions
from ..application.usecases.plan_study_path import PlanStudyPath
from ..application.usecases.scan_site import ScanSite
from ..application.usecases.usage_report import UsageReport, fun_fact
from ..settings import PROJECT_ROOT, Settings, load_settings, set_active_model, set_budget


@dataclass
class Usecases:
    """HTTP 层可调用的全部用例，由装配根一次性注入。

    LLM 相关的用例（identify/generate_material/study_path）在密钥缺失时
    会是 None——对应接口返回 503 和配置指引，而不是整个服务起不来。
    """

    scan: ScanSite | None = None
    identify: IdentifyCompetitions | None = None
    report: GenerateReport | None = None
    cost_report: CostReport | None = None
    sessions: SessionReport | None = None
    usage_report: UsageReport | None = None
    chat: ChatService | None = None
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


class IdentifyRequest(BaseModel):
    limit: int = 3


class SwitchModelRequest(BaseModel):
    name: str


class BudgetRequest(BaseModel):
    yuan: float | None = None  # null = 不限预算


class ChatRequest(BaseModel):
    message: str
    session_id: int | None = None  # 不传 = 开新聊天会话


class ChatCloseRequest(BaseModel):
    session_id: int


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


def _task_cost_to_dict(bucket) -> dict:
    """TaskCost 小计 -> 响应字典（cost_yuan 允许为 None：没配单价算不出钱）。"""
    return {
        "calls": bucket.calls,
        "prompt_tokens": bucket.prompt_tokens,
        "completion_tokens": bucket.completion_tokens,
        "cost_yuan": bucket.cost_yuan,
    }


def parse_date_safely(text: str | None):
    """把 YYYY-MM-DD 字符串转成 date；格式不对返回 None（交给调用方报 422）。"""
    if text is None:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


class MarkdownResponse(PlainTextResponse):
    """纯文本响应的变体：Content-Type 标为 text/markdown。"""

    media_type = "text/markdown"


def create_app(settings: Settings | None = None, usecases: Usecases | None = None) -> FastAPI:
    """创建 FastAPI 应用。usecases 由装配根注入；测试时可以传假用例。"""
    app = FastAPI(
        title="contest_agent",
        version="0.2.0",
        description="比赛 Agent 助手 API",
    )

    @app.get("/health")
    def health() -> dict:
        """健康检查：监控/网关定期来戳一下，确认服务活着。"""
        payload: dict = {"status": "ok", "version": "0.2.0"}
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

    @app.get("/cost")
    def cost(task: str | None = None, date: str | None = None) -> dict:
        """查询 LLM 成本台账（M1）。

        可选参数：task=identify|generate|study_path 按任务过滤；
        date=YYYY-MM-DD 只看某天。都不传 = 全部账单。
        """
        if usecases is None or usecases.cost_report is None:
            raise HTTPException(503, "成本查询未装配")
        on_date = parse_date_safely(date)
        if date is not None and on_date is None:
            raise HTTPException(422, f"日期格式不对：{date!r}，应为 YYYY-MM-DD")
        if task is not None and task not in TASK_TYPES:
            raise HTTPException(422, f"任务名 {task!r} 不认识，可选：{'/'.join(TASK_TYPES)}")

        summary = usecases.cost_report.execute(task_type=task, on_date=on_date)
        return {
            "total": _task_cost_to_dict(summary.total),
            "by_task": {name: _task_cost_to_dict(c) for name, c in summary.by_task.items()},
            "by_model": {name: _task_cost_to_dict(c) for name, c in summary.by_model.items()},
        }

    @app.get("/sessions")
    def sessions(limit: int = 20) -> dict:
        """最近的任务会话列表（M2）：编号、任务、状态、事件数、花费。"""
        if usecases is None or usecases.sessions is None:
            raise HTTPException(503, "会话查询未装配")
        items = usecases.sessions.list_recent(limit=limit)
        return {
            "count": len(items),
            "sessions": [
                {
                    "id": s.id,
                    "task_type": s.task_type,
                    "note": s.note,
                    "status": s.status,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                    "event_count": s.event_count,
                    "cost_yuan": s.cost_yuan,
                    "llm_calls": s.llm_calls,
                }
                for s in items
            ],
        }

    @app.get("/sessions/{session_id}")
    def session_detail(session_id: int) -> dict:
        """一个会话的完整轨迹（M2）：按序排好的全部事件，回放用。"""
        if usecases is None or usecases.sessions is None:
            raise HTTPException(503, "会话查询未装配")
        try:
            summary, events = usecases.sessions.detail(session_id)
        except KeyError as error:
            raise HTTPException(404, str(error))
        return {
            "session": {
                "id": summary.id,
                "task_type": summary.task_type,
                "note": summary.note,
                "status": summary.status,
                "started_at": summary.started_at.isoformat() if summary.started_at else None,
                "ended_at": summary.ended_at.isoformat() if summary.ended_at else None,
                "cost_yuan": summary.cost_yuan,
            },
            "events": [
                {"seq": e.seq, "kind": e.kind, "payload": e.payload,
                 "created_at": e.created_at.isoformat() if e.created_at else None}
                for e in events
            ],
        }

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
            "pptx_file": result.pptx_file,
            "pptx_hint": result.pptx_hint,
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

    # ---------- M4：前端面板接口 ----------

    @app.get("/api/usage/summary")
    def usage_summary(range: str = "all") -> dict:
        """Overview 面板数据包：六统计 + 逐日热力图 + 周对比 + 趣味文案。"""
        if usecases is None or usecases.usage_report is None:
            raise HTTPException(503, "用量查询未装配")
        try:
            summary = usecases.usage_report.execute(range_name=range)
        except ValueError as error:
            raise HTTPException(422, str(error))
        return {
            "range": summary.range,
            "sessions": summary.sessions,
            "messages": summary.messages,
            "total_tokens": summary.total_tokens,
            "active_days": summary.active_days,
            "peak_hour": summary.peak_hour,
            "favorite_model": summary.favorite_model,
            "by_model": summary.by_model,
            "daily": [{"date": d.date, "tokens": d.tokens} for d in summary.daily],
            "week_ratio": summary.week_ratio,
            "fun_fact": fun_fact(summary),
        }

    @app.get("/api/config")
    def get_config() -> dict:
        """当前配置的脱敏视图（Settings 面板数据源）：绝不含密钥本身。"""
        current = load_settings()
        return {
            "active_model": current.active_model,
            "models": [
                {
                    "name": name,
                    "model": profile.model,
                    "has_key": profile.resolve_api_key() is not None,
                    "input_price_per_m": profile.input_price_per_m,
                    "output_price_per_m": profile.output_price_per_m,
                }
                for name, profile in current.yaml_config.models.items()
            ],
            "routing": current.yaml_config.routing,
            "budget_per_task_yuan": current.yaml_config.budget_per_task_yuan,
            "permissions": current.yaml_config.permissions.model_dump(),
            "push": {
                "webhook": current.yaml_config.push.webhook_url is not None,
                "file_dir": current.yaml_config.push.file_dir,
                "smtp": current.yaml_config.push.smtp is not None,
            },
            "context_trigger_ratio": current.yaml_config.context.trigger_ratio,
        }

    @app.post("/api/config/model")
    def switch_model(req: SwitchModelRequest) -> dict:
        """切换当前生效的模型档案（写回 config.yaml，沿 sai model use 的逻辑）。"""
        try:
            set_active_model(req.name)
        except KeyError as error:
            raise HTTPException(422, str(error))
        return {"active_model": req.name}

    @app.post("/api/config/budget")
    def update_budget(req: BudgetRequest) -> dict:
        """更新单任务预算上限（写回 config.yaml；null = 不限）。"""
        try:
            set_budget(req.yuan)
        except ValueError as error:
            raise HTTPException(422, str(error))
        return {"budget_per_task_yuan": req.yuan}

    @app.post("/identify")
    def identify_endpoint(req: IdentifyRequest) -> dict:
        """扫描并识别比赛（与 sai identify 同款；多次 LLM 调用，可能耗时数十秒）。"""
        if usecases is None or usecases.identify is None:
            raise HTTPException(
                503, "识别需要 LLM 密钥：请在 .env 里配置 DEEPSEEK_API_KEY"
            )
        try:
            outcomes = usecases.identify.execute(limit=req.limit)
        except (ConnectionError, RuntimeError) as error:
            raise HTTPException(502, str(error))
        type_names = {"deliverable": "交付物型", "exam": "考试型"}
        return {
            "count": len(outcomes),
            "last_sync": usecases.identify.last_sync,
            "budget_error": usecases.identify.budget_error,
            "outcomes": [
                {
                    "title": o.notice.title,
                    "url": o.notice.source_url,
                    "is_competition": o.is_competition,
                    "from_memory": o.from_memory,
                    "llm_called": o.llm_called,
                    "reason": o.reason,
                    "card": (
                        {
                            "name": o.competition.name,
                            "type": type_names.get(o.competition.type, o.competition.type),
                            "deadline": (o.competition.deadline.isoformat()
                                         if o.competition.deadline else None),
                        }
                        if o.competition is not None
                        else None
                    ),
                }
                for o in outcomes
            ],
        }

    @app.post("/api/chat")
    def chat(req: ChatRequest):
        """自由对话（SSE 逐 token 流式）。

        前端用 fetch 读响应流：每帧 `data: {json}\\n\\n`，
        type = session(开场带会话号) / token(文本增量) / done / error。
        """
        if usecases is None or usecases.chat is None:
            raise HTTPException(
                503, "对话需要 LLM 密钥：请在 .env 里配置 DEEPSEEK_API_KEY"
            )
        chat_service = usecases.chat
        session_id = req.session_id
        if session_id is None:
            session_id = chat_service.open_session()

        def frame(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        def generate():
            yield frame({"type": "session", "session_id": session_id})
            try:
                for chunk in chat_service.stream_reply(session_id, req.message):
                    yield frame(chunk)
            except Exception as error:  # 兜底：流中断也要给前端一个明确结束帧
                yield frame({"type": "error", "error": str(error)})

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post("/api/chat/close")
    def chat_close(req: ChatCloseRequest) -> dict:
        """正常收尾一个聊天会话（前端点"新会话"时调用）。"""
        if usecases is None or usecases.chat is None:
            raise HTTPException(503, "对话未装配")
        usecases.chat.close_session(req.session_id)
        return {"closed": req.session_id}

    # ---------- 前端静态托管：构建产物存在才挂载，`sai serve` 单端口全搞定 ----------

    dist_dir = PROJECT_ROOT / "frontend" / "dist"
    if dist_dir.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")

    return app
