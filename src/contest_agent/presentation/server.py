"""FastAPI 呈现层：把 HTTP 请求翻译成对内部功能的调用。

呈现层纪律：这里只做三件事——解析请求参数、调用内部功能、组装响应。
不写任何业务逻辑（业务在 application 层的用例里）。
这样同一个功能既能被 HTTP 接口用（server.py），也能被命令行用（cli.py）。

P0 只实现了 /health；P6 会补 /scan、/competitions、/generate。
"""

from __future__ import annotations

from fastapi import FastAPI

from ..settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建并返回 FastAPI 应用（"工厂函数"写法）。

    为什么不直接在模块顶层写 app = FastAPI() 了事？
    因为测试时想传一份测试专用的配置进来；工厂函数把"创建"这件事
    变成了可控制的调用，正式运行时由 composition.py 统一调用并传真实配置。
    """
    app = FastAPI(
        title="contest_agent",
        version="0.1.0",
        description="比赛 Agent 助手",
    )

    @app.get("/health")  # 把下面的函数注册为 GET /health 的处理器
    def health() -> dict:
        """健康检查接口：监控/网关定期来戳一下，确认服务活着。"""
        payload: dict = {"status": "ok", "version": "0.1.0"}
        # settings 不为 None 说明是经过装配根创建的（正式运行），
        # 顺手汇报当前用的模型档案，排查问题时一眼能看出"用的谁"
        if settings is not None:
            payload["active_model"] = settings.active_model
        return payload

    return app
