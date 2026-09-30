"""FastAPI 呈现层：/health /scan /competitions /generate（P0 仅 /health）。

呈现层不含业务逻辑：只做 HTTP <-> 用例调用的翻译，
业务能力由 composition.py 注入的用例提供。
"""

from __future__ import annotations

from fastapi import FastAPI

from ..settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="contest_agent", version="0.1.0", description="比赛 Agent 助手")

    @app.get("/health")
    def health() -> dict:
        payload: dict = {"status": "ok", "version": "0.1.0"}
        if settings is not None:
            payload["active_model"] = settings.active_model
        return payload

    # P6 在这里补 /scan /competitions /generate
    return app
