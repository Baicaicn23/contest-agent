"""M4 后端验收测试：UsageReport 聚合、配置读写接口、/identify 端点。

- 聚合用例用真 SQLite 内存库喂精心构造的流水/会话，逐项核对六统计；
- 配置写入用临时 yaml 测"按行替换保注释"；
- HTTP 端点用假用例 + monkeypatch 测翻译层（绝不真写仓库的 config.yaml）。
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contest_agent.application.usecases.usage_report import UsageReport, fun_fact
from contest_agent.domain.entities import UsageEntry
from contest_agent.infrastructure.persistence.repository import (
    SqliteSessionRepository,
    SqliteUsageRepository,
)
from contest_agent.presentation.server import Usecases, create_app
from contest_agent.settings import load_settings, load_yaml_config, set_budget


# ---------- 聚合用例（真内存库） ----------


def _seed(db_file: str):
    """构造跨两天/两个模型/两个小时的流水 + 两个会话。

    注意：仓储在这里建好并返回给测试复用——如果测试里再按同一个
    :memory: 连接串建新仓储，那是另一个独立的库，互相看不见
    （M2 踩过的坑）。
    """
    usage = SqliteUsageRepository(db_file)
    sessions = SqliteSessionRepository(db_file)

    # 动态日期（修复跨月过期）：取本周一 21 点 + 周二 10 点——
    # 写死日期的版本在跨月后（9→10 月）"本周"判断失效过一次
    from datetime import timedelta

    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    d1 = monday.replace(hour=21, minute=0)          # 本周一晚 9 点
    d2 = d1 + timedelta(days=1, hours=-11)          # 周二上午 10 点
    usage.record(UsageEntry("identify", "deepseek", "deepseek-chat", 1000, 500, 0.006,
                            created_at=d1, session_id=1))
    usage.record(UsageEntry("generate", "deepseek", "deepseek-chat", 3000, 1500, 0.018,
                            created_at=d1, session_id=1))
    usage.record(UsageEntry("chat", "qwen", "qwen-plus", 800, 200, 0.001,
                            created_at=d2, session_id=2))

    s1 = sessions.create_session("identify", "limit=2")
    assert s1 == 1
    sessions.create_session("chat", "")
    return usage, sessions


def test_usage_report_aggregates_six_stats() -> None:
    db = "sqlite:///:memory:"
    usage, sessions = _seed(db)
    report = UsageReport(usage, sessions)

    summary = report.execute("all")

    assert summary.sessions == 2
    assert summary.messages == 3
    assert summary.total_tokens == 1000 + 500 + 3000 + 1500 + 800 + 200
    assert summary.active_days == 2
    # 21 点两笔共 6000 token > 10 点一笔 1000：高峰是 21 点
    assert summary.peak_hour == 21
    # deepseek 共 6000 > qwen 1000
    assert summary.favorite_model == "deepseek-chat"
    assert summary.by_model == {"deepseek-chat": 6000, "qwen-plus": 1000}
    from datetime import timedelta as _td

    _monday = datetime.now() - _td(days=datetime.now().weekday())
    assert [d.date for d in summary.daily] == [
        _monday.date().isoformat(),
        (_monday + _td(days=1, hours=-11)).date().isoformat(),
    ]


def test_usage_report_range_filters_and_week_ratio() -> None:
    db = "sqlite:///:memory:"
    usage, sessions = _seed(db)
    report = UsageReport(usage, sessions)

    # 7 天范围：造的流水都在近两天，应全部命中
    summary = report.execute("7d")
    assert summary.messages == 3
    # 周对比：9/29-30 同属一周（周二/周三），全部算本周，上周为 0
    assert summary.this_week_tokens == 7000
    assert summary.last_week_tokens == 0
    assert summary.week_ratio is None

    with pytest.raises(ValueError):
        report.execute("100d")


def test_fun_fact_copies() -> None:
    from contest_agent.application.usecases.usage_report import UsageSummary

    s = UsageSummary(this_week_tokens=800, last_week_tokens=200, week_ratio=4.0)
    assert "4.0 倍" in fun_fact(s)
    s2 = UsageSummary(this_week_tokens=100, last_week_tokens=400, week_ratio=0.25)
    assert "省得很稳" in fun_fact(s2)
    s3 = UsageSummary(this_week_tokens=500, last_week_tokens=0, week_ratio=None)
    assert "第一笔" in fun_fact(s3)


# ---------- set_budget：按行替换保注释 ----------


def test_set_budget_roundtrip_keeps_comments(tmp_path: Path) -> None:
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(
        "# 顶部注释不能丢\n"
        "active_model: deepseek\n"
        "models:\n"
        "  deepseek:\n"
        "    base_url: https://api.example.com\n"
        "    api_key_env: EXAMPLE_KEY\n"
        "    model: example-chat\n"
        "sources: []\n"
        "# 单任务预算上限（元）——注释也不能丢\n"
        "budget_per_task_yuan: null\n",
        encoding="utf-8",
    )

    set_budget(5.0, config_path=yaml_file)
    text = yaml_file.read_text(encoding="utf-8")
    assert "budget_per_task_yuan: 5.0" in text
    assert "注释也不能丢" in text                     # 注释原样保留
    cfg = load_yaml_config(yaml_file)
    assert cfg.budget_per_task_yuan == 5.0

    set_budget(None, config_path=yaml_file)
    assert "budget_per_task_yuan: null" in yaml_file.read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        set_budget(-1, config_path=yaml_file)


# ---------- HTTP 端点（假用例 + monkeypatch，绝不写真 config.yaml） ----------


class FakeUsageReport:
    def execute(self, range_name="all"):
        from contest_agent.application.usecases.usage_report import RANGES, UsageSummary

        if range_name not in RANGES:      # 和真用例一样：坏 range 当场拒绝
            raise ValueError(f"range 只支持 {'/'.join(RANGES)}")
        summary = UsageSummary(range=range_name, sessions=2, messages=13,
                               total_tokens=189500, active_days=1, peak_hour=21,
                               favorite_model="deepseek-chat",
                               week_ratio=4.0)
        return summary


class FakeIdentify:
    last_sync = {"new": 1, "existing": 2}
    budget_error = None

    def execute(self, limit=3):
        from contest_agent.domain.entities import Competition, Notice
        notice = Notice(source_url="u1", title="测试杯报名通知")
        return [
            type("O", (), {
                "notice": notice, "is_competition": True, "from_memory": False,
                "llm_called": True, "reason": "是比赛",
                "competition": Competition(name="测试杯", notice_url="u1", type="exam"),
            })(),
        ]


def _client() -> TestClient:
    return TestClient(create_app(load_settings(),
                                 Usecases(usage_report=FakeUsageReport(),
                                          identify=FakeIdentify())))


def test_usage_summary_endpoint() -> None:
    resp = _client().get("/api/usage/summary", params={"range": "7d"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "7d"
    assert body["total_tokens"] == 189500
    assert "4.0 倍" in body["fun_fact"]

    assert _client().get("/api/usage/summary", params={"range": "坏值"}).status_code == 422


def test_config_endpoint_is_sanitized() -> None:
    resp = _client().get("/api/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["active_model"]
    assert len(body["models"]) >= 1
    assert "api_key" not in str(body)                # 密钥绝不出现
    assert "routing" in body and "permissions" in body and "push" in body


def test_switch_model_endpoint(monkeypatch) -> None:
    import contest_agent.presentation.server as server_module

    called = []
    monkeypatch.setattr(server_module, "set_active_model",
                        lambda name: called.append(name))

    resp = _client().post("/api/config/model", json={"name": "qwen"})
    assert resp.status_code == 200
    assert resp.json() == {"active_model": "qwen"}
    assert called == ["qwen"]


def test_budget_endpoint(monkeypatch) -> None:
    import contest_agent.presentation.server as server_module

    called = []
    monkeypatch.setattr(server_module, "set_budget", lambda yuan: called.append(yuan))

    resp = _client().post("/api/config/budget", json={"yuan": 5.0})
    assert resp.status_code == 200
    assert called == [5.0]

    resp2 = _client().post("/api/config/budget", json={"yuan": None})
    assert resp2.status_code == 200
    assert called == [5.0, None]


def test_identify_endpoint_shape() -> None:
    resp = _client().post("/identify", json={"limit": 1})

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    outcome = body["outcomes"][0]
    assert outcome["is_competition"] is True
    assert outcome["card"]["name"] == "测试杯"
