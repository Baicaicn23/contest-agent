"""P0 验收测试：/health 可用、装配根可跑、config.yaml 可解析。

测试先行纪律从 P0 开始：每个阶段的验收标准都落成 pytest。
"""

from fastapi.testclient import TestClient

from contest_agent.composition import build_app
from contest_agent.settings import load_yaml_config


def test_health_returns_ok() -> None:
    client = TestClient(build_app())
    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["active_model"]  # settings 已接通装配根


def test_yaml_config_parses() -> None:
    cfg = load_yaml_config()

    assert cfg.active_model in cfg.models, "active_model 必须指向一个已定义的模型档案"
    assert cfg.sources, "至少配置一个站点源"
    for source in cfg.sources:
        assert source.request_interval >= 1.5, "爬虫合规：请求间隔不得低于 1.5 秒"


def test_active_profile_resolves() -> None:
    from contest_agent.settings import load_settings

    settings = load_settings()
    profile = settings.active_profile

    assert profile.api_key_env  # 密钥只存环境变量名，不存密钥本身
