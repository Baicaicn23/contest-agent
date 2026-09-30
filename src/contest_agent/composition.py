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

from fastapi import FastAPI

from .application.usecases.scan_site import ScanSite
from .infrastructure.crawler.notice_source import RequestsNoticeSource
from .presentation.server import create_app
from .settings import Settings, load_settings

__all__ = ["build_app", "build_notice_source", "build_scan_usecase", "app"]


def load_settings_or_raise() -> Settings:
    """读配置。单独包一层只是为了让装配代码读起来更顺，没有别的魔法。"""
    return load_settings()


def build_notice_source() -> RequestsNoticeSource:
    """组装爬虫：按配置文件里的第一个站点源创建（P1）。

    目前只有一个源；v2 多校源时，这里会变成"按源名创建"的字典/循环。
    """
    settings = load_settings_or_raise()
    return RequestsNoticeSource(settings.yaml_config.sources[0])


def build_scan_usecase() -> ScanSite:
    """组装 scan_site 用例：把爬虫递给用例（P1）。

    注意依赖方向：用例只认识 NoticeSourcePort 接口，
    RequestsNoticeSource 这个具体类名只出现在本文件里。
    """
    return ScanSite(build_notice_source())


def build_app() -> FastAPI:
    """组装整个应用，返回配置齐全的 FastAPI 实例。"""
    settings = load_settings_or_raise()

    # P2: llm = OpenAiCompatLlm(settings.active_profile)                 # LLM 实现"会调模型"
    # P3: repo = SqliteCompetitionRepository(settings.database_url)      # 仓储实现"会存比赛"
    # P4/P5: 用例装配手写 harness 与 skills，交给接口层

    return create_app(settings)


# 模块级 app：cli.py 里 uvicorn.run("contest_agent.composition:app")
# 按这个字符串来启动服务，找到的就是这个变量
app = build_app()
