"""P6 验收测试：FastAPI 接口的回归测试（假用例，离线、毫秒级）。

测的是"HTTP ↔ 用例"的翻译层：路由对不对、参数怎么传、异常映射到
什么状态码。用例本身已被各自阶段的测试覆盖，这里用简单假对象冒充。
"""

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from contest_agent.application.usecases.generate_material import MaterialResult
from contest_agent.application.usecases.plan_study_path import StudyPathResult
from contest_agent.presentation.server import Usecases, create_app
from contest_agent.settings import load_settings


# ---------- 假用例（每个只实现接口会调到的方法） ----------


class FakeScan:
    last_sync = {"new": 3, "existing": 0}

    def execute(self, limit: int = 10, detail_indexes=None) -> list:
        from contest_agent.domain.entities import Notice

        return [
            Notice(source_url=f"https://x.edu.cn/n{i}", title=f"竞赛通知{i}")
            for i in range(1, min(limit, 3) + 1)
        ]


class FakeReport:
    class _Repo:
        def list_all(self) -> list:
            from contest_agent.domain.entities import Competition

            return [Competition(name="数媒竞赛", notice_url="u1", type="deliverable")]

    repository = _Repo()

    def execute(self) -> str:
        return "# 🏆 比赛情报报告\n\n共 1 场比赛"


class FakeGenerate:
    def execute(self, skill_name: str, competition_name: str | None = None) -> MaterialResult:
        if skill_name == "不存在的技能":
            raise FileNotFoundError("技能不存在")
        return MaterialResult(
            final_text="完成",
            success=True,
            skill_name=skill_name,
            competition_name="数媒竞赛",
            tool_trace=["list_competitions()"],
        )


class FakeStudyPath:
    def execute(self, competition_name: str | None = None) -> StudyPathResult:
        return StudyPathResult(
            final_text="路径已生成",
            success=True,
            competition_name="蓝桥杯",
            citations=[{"url": "https://ok.example.com", "ok": True, "note": "正常"}],
        )


@dataclass
class ExplodingIdentify:
    """模拟"密钥缺失导致用例未装配"之外的业务错误。"""

    def execute(self, limit: int = 5) -> list:
        raise RuntimeError("库里还没有比赛卡片")


class FakeCostReport:
    """假成本用例：返回一笔固定账单，测 /cost 的翻译层。"""

    def execute(self, task_type=None, on_date=None):
        from contest_agent.application.usecases.cost_report import CostSummary, TaskCost

        bucket = TaskCost(calls=2, prompt_tokens=3000, completion_tokens=800, cost_yuan=0.0184)
        return CostSummary(total=bucket, by_task={"identify": bucket}, by_model={})


def _client(usecases: Usecases | None):
    from contest_agent.presentation.server import create_app as _ca

    return TestClient(_ca(load_settings(), usecases))


# ---------- 接口行为 ----------


def test_health_ok() -> None:
    resp = _client(None).get("/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_scan_endpoint_returns_notices_and_sync() -> None:
    resp = _client(Usecases(scan=FakeScan(), report=FakeReport())).post(
        "/scan", json={"limit": 3}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert body["sync"] == {"new": 3, "existing": 0}
    assert body["notices"][0]["title"] == "竞赛通知1"


def test_competitions_and_report_endpoints() -> None:
    client = _client(Usecases(report=FakeReport()))

    comps = client.get("/competitions").json()
    assert comps["count"] == 1
    assert comps["competitions"][0]["name"] == "数媒竞赛"

    report = client.get("/report")
    assert "比赛情报报告" in report.text


def test_generate_endpoint_maps_success() -> None:
    client = _client(Usecases(generate_material=FakeGenerate()))

    resp = client.post("/generate", json={"skill": "ppt-outline"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["tool_trace"] == ["list_competitions()"]


def test_generate_endpoint_maps_skill_not_found_to_404() -> None:
    client = _client(Usecases(generate_material=FakeGenerate()))

    resp = client.post("/generate", json={"skill": "不存在的技能"})

    assert resp.status_code == 404


def test_study_path_endpoint_maps_success() -> None:
    client = _client(Usecases(study_path=FakeStudyPath()))

    resp = client.post("/study-path", json={})

    assert resp.status_code == 200
    assert resp.json()["citations"][0]["ok"] is True


def test_missing_usecase_returns_503() -> None:
    """密钥未配置的降级：LLM 相关接口返回 503 和配置指引。"""
    client = _client(Usecases())  # 全部用例未装配

    resp = client.post("/generate", json={"skill": "ppt-outline"})

    assert resp.status_code == 503
    assert "DEEPSEEK_API_KEY" in resp.json()["detail"]


# ---------- /cost 接口（M1） ----------


def test_cost_endpoint_returns_bill() -> None:
    """账单查询：参数透传 + 汇总结构原样返回。"""
    client = _client(Usecases(cost_report=FakeCostReport()))

    resp = client.get("/cost", params={"task": "identify"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"]["calls"] == 2
    assert body["by_task"]["identify"]["cost_yuan"] == pytest.approx(0.0184)


def test_cost_endpoint_validates_params() -> None:
    """参数校验：任务名不认识、日期格式不对都返回 422。"""
    client = _client(Usecases(cost_report=FakeCostReport()))

    assert client.get("/cost", params={"task": " nonsense"}).status_code == 422
    assert client.get("/cost", params={"date": "2026/09/30"}).status_code == 422


def test_cost_endpoint_503_when_not_wired() -> None:
    """用例未装配（不应发生，但接口要有降级姿态）。"""
    resp = _client(Usecases()).get("/cost")

    assert resp.status_code == 503


def test_build_app_smoke() -> None:
    """装配根整体冒烟：build_app 出来的真实应用 /health 可用。"""
    from contest_agent.composition import build_app

    resp = TestClient(build_app()).get("/health")

    assert resp.status_code == 200
