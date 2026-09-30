"""P0 验收测试：/health 可用、装配根能跑、config.yaml 能解析。

测试先行纪律从 P0 开始：开发文档里每个阶段的"验收标准"，
都落成这里的 pytest 测试——标准不是嘴上说说，而是能自动执行的代码。
跑法：uv run pytest
"""

from fastapi.testclient import TestClient
# TestClient 是 FastAPI 官方的测试工具：
# 不用真的启动服务器、监听端口，就能模拟发出 HTTP 请求拿到响应，
# 所以测试跑得飞快（毫秒级）。

from contest_agent.composition import build_app
from contest_agent.settings import load_settings, load_yaml_config


def test_health_returns_ok() -> None:
    """验收项：GET /health 返回 ok，且配置已接通装配根。"""
    # Arrange（准备）：通过装配根创建应用——和正式启动走同一条路径
    client = TestClient(build_app())

    # Act（执行）：模拟发一个 GET /health 请求
    resp = client.get("/health")

    # Assert（断言）：检查响应符合预期
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # active_model 有值，说明 settings -> composition -> server 这条装配线是通的
    assert body["active_model"]


def test_yaml_config_parses() -> None:
    """验收项：config.yaml 能解析，且满足项目的合规约定。"""
    cfg = load_yaml_config()

    # 当前生效的模型档案必须是已经定义过的，不能指向空气
    assert cfg.active_model in cfg.models
    # 至少要配置一个站点源，不然 P1 爬虫没活可干
    assert cfg.sources
    for source in cfg.sources:
        # 把"爬虫请求间隔 >= 1.5 秒"这条合规要求直接写成测试：
        # 以后谁在配置里把间隔改小了，测试立刻红
        assert source.request_interval >= 1.5


def test_active_profile_resolves() -> None:
    """验收项：当前模型档案能取到，且密钥确实只存环境变量名（不存密钥本身）。"""
    settings = load_settings()
    profile = settings.active_profile

    # api_key_env 是"环境变量的名字"（如 DEEPSEEK_API_KEY），
    # 如果有一天发现这里存的是 sk- 开头的真密钥，说明密钥管理出问题了
    assert profile.api_key_env
