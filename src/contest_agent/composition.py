"""装配根（composition root）：整个项目唯一"知道具体实现"的地方。

单向装配纪律：settings -> 爬虫 -> LLM 工厂 -> 仓储 -> 用例 -> FastAPI app。
依赖方向永远向内：presentation 只认用例，用例只认 domain 端口，
infrastructure 实现端口——除此之外任何模块不得互相伸手（Globex 核心纪律）。

P0 只接通 settings 与呈现层；P1-P5 按阶段往里装配。
"""

from __future__ import annotations

from fastapi import FastAPI

from .presentation.server import create_app
from .settings import load_settings

__all__ = ["build_app", "app"]


def build_app() -> FastAPI:
    settings = load_settings()
    # P1: crawler = RequestsNoticeSource(settings.yaml_config.sources)
    # P2: llm = OpenAiCompatLlm(settings.active_profile)
    # P3: repo = SqliteCompetitionRepository(settings.database_url)
    # P4/P5: usecases 装配 harness 与 skills
    return create_app(settings)


app = build_app()
