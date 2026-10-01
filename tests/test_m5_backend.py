"""M5 后端验收测试：工作台（项目/搜索/通知/技能/文件/git）、插件开关、完全访问总闸。

- WorkspaceService 用真 SQLite 内存库 + 临时目录 + 假 git 回调；
- HTTP 端点用假用例/monkeypatch，绝不写真仓库的 config.yaml；
- set_feature/set_access_full 用临时 yaml 测行级写入。
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contest_agent.application.usecases.workspace import WorkspaceService, _card_key
from contest_agent.domain.entities import Competition, Notice, UsageEntry
from contest_agent.infrastructure.persistence.repository import (
    SqliteCompetitionRepository,
    SqliteNoticeRepository,
    SqliteProjectRepository,
    SqliteSessionRepository,
    SqliteUsageRepository,
)
from contest_agent.presentation.server import Usecases, create_app
from contest_agent.settings import (
    load_settings,
    load_yaml_config,
    set_access_full,
    set_feature,
)


# ---------- WorkspaceService（真内存库） ----------


@pytest.fixture
def workspace(tmp_path: Path):
    db = "sqlite:///:memory:"
    comps = SqliteCompetitionRepository(db)
    sessions = SqliteSessionRepository(db)
    notices = SqliteNoticeRepository(db)
    projects = SqliteProjectRepository(db)
    usage = SqliteUsageRepository(db)

    today = datetime.now()
    comps.save_if_absent(Competition(
        name="数媒竞赛", notice_url="https://x/shumei", type="deliverable",
        deadline=today + timedelta(days=1),
    ))
    notices.save_notice_if_absent(Notice(
        source_url="https://x/shumei", title="关于数媒竞赛的通知",
        published_at=today,
    ))
    sessions.create_session("chat", "数媒竞赛讨论")

    service = WorkspaceService(
        competition_repository=comps,
        session_archive=sessions,
        notice_repository=notices,
        project_store=projects,
        usage_repository=usage,
        memory=None,
        skills_dir=tmp_path / "skills",
        output_dir=tmp_path / "out",
        git_runner=lambda: "feature/m5",
    )
    return service, comps, sessions, notices, projects, tmp_path


def test_projects_auto_from_cards_and_manual(workspace) -> None:
    """比赛卡自动派生项目；手动新建追加；会话归属计数。"""
    service, comps, sessions, _, projects, _ = workspace

    # 手动建一个项目 + 把会话绑到数媒卡项目
    manual = service.create_project("我的实验田")
    card_key = "card:" + _card_key(comps.list_all()[0]).split(":", 1)[1]
    assert service.bind_session(1, card_key) is True

    result = service.list_projects()
    keys = {p.key: p for p in result}
    assert any(p.source == "auto" and p.name == "数媒竞赛" for p in result)
    assert keys[manual.key].name == "我的实验田"
    assert keys[card_key].sessions == 1             # 会话已归属

    # 不存在的项目键绑定 → 报错
    with pytest.raises(ValueError):
        service.bind_session(1, "manual:999")


def test_search_across_sessions_cards_notices(workspace) -> None:
    service, *_ = workspace
    result = service.search("数媒")

    assert any("数媒" in c["name"] for c in result["cards"])
    assert any("数媒" in n["title"] for n in result["notices"])

    empty = service.search("")
    assert empty == {"sessions": [], "cards": [], "notices": []}


def test_notifications_counts_urgent(workspace) -> None:
    """紧急截止（≤1 天）进通知。"""
    service, *_ = workspace
    data = service.notifications()
    assert len(data["urgent_deadlines"]) == 1
    assert data["urgent_deadlines"][0]["remaining"] == 1


def test_list_skills_parses_frontmatter(workspace, tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "demo.md").write_text(
        "---\nname: demo\ndescription: 演示技能\n---\n正文", encoding="utf-8")
    service, *_ = workspace
    service.skills_dir = skills_dir

    skills = service.list_skills()
    assert skills[0]["name"] == "demo"
    assert skills[0]["description"] == "演示技能"


def test_list_files_and_git_branch(workspace, tmp_path: Path) -> None:
    service, *_ = workspace
    out = tmp_path / "out"
    out.mkdir()
    (out / "ppt-outline.pptx").write_bytes(b"x")

    files = service.list_files()
    assert files[0]["name"] == "ppt-outline.pptx"
    assert service.git_branch() == "feature/m5"     # 假 git 回调


# ---------- 插件注册表 ----------


def test_plugins_status_reflects_config(workspace) -> None:
    from contest_agent.settings import load_yaml_config

    service, *_ = workspace
    # 真配置：features 全缺省=True，push.file_dir 有值 → file 启用
    status = {p["id"]: p for p in service.plugins_status(load_yaml_config(Path("config.yaml")))}
    assert status["deadlines"]["enabled"] is True
    assert status["deadlines"]["toggleable"] is True
    assert status["file"]["enabled"] is True
    assert status["webhook"]["enabled"] is False
    assert status["smtp"]["toggleable"] is False    # 通道类由 push 配置驱动，不给按钮


# ---------- set_feature / set_access_full（临时 yaml） ----------


def _mini_yaml(tmp_path: Path) -> Path:
    f = tmp_path / "config.yaml"
    f.write_text(
        "active_model: deepseek\n"
        "models:\n  deepseek:\n    base_url: https://x\n"
        "    api_key_env: K\n    model: m\n"
        "sources: []\n"
        "permissions:\n  confirm_tools: []\n  unattended_deny_tools: []\n"
        "access_full: false\n"
        "features:\n  eval: true\n",
        encoding="utf-8",
    )
    return f


def test_set_feature_roundtrip(tmp_path: Path) -> None:
    f = _mini_yaml(tmp_path)
    set_feature("eval", False, config_path=f)
    text = f.read_text(encoding="utf-8")
    assert "eval: false" in text
    assert "access_full: false" in text             # 别的行不动

    set_feature("pptx", True, config_path=f)        # 段内没有的键 → 插入
    assert "pptx: true" in f.read_text(encoding="utf-8")
    cfg = load_yaml_config(f)
    assert cfg.features == {"eval": False, "pptx": True}


def test_set_access_full_roundtrip(tmp_path: Path) -> None:
    f = _mini_yaml(tmp_path)
    set_access_full(True, config_path=f)
    assert "access_full: true" in f.read_text(encoding="utf-8")
    cfg = load_yaml_config(f)
    assert cfg.access_full is True


# ---------- HTTP 端点（假用例） ----------


class FakeWorkspace:
    def list_projects(self):
        from contest_agent.domain.entities import ProjectInfo
        return [ProjectInfo(key="card:abc", name="数媒竞赛", source="auto", sessions=2)]

    def create_project(self, name):
        from contest_agent.domain.entities import ProjectInfo
        return ProjectInfo(key="manual:9", name=name, source="manual")

    def bind_session(self, session_id, project_key):
        if project_key == "manual:999":
            raise ValueError("项目不存在")
        return True

    def search(self, q):
        return {"sessions": [], "cards": [{"name": q}], "notices": []}

    def notifications(self):
        return {"urgent_deadlines": [{"name": "A", "label": "🔴", "remaining": 0}],
                "completed_recently": 3}

    def list_skills(self):
        return [{"file": "a.md", "name": "a", "description": ""}]

    def list_files(self):
        return [{"name": "x.md", "size": 3, "modified": "2026-10-01T00:00:00"}]

    def git_branch(self):
        return "main"

    def plugins_status(self, yaml_config):
        return [
            {"id": "eval", "name": "识别评测", "desc": "", "category": "治理",
             "kind": "feature", "key": "eval", "enabled": True, "toggleable": True},
            {"id": "smtp", "name": "邮件推送", "desc": "", "category": "推送",
             "kind": "push", "key": "smtp", "enabled": False, "toggleable": False},
        ]


def _client() -> TestClient:
    return TestClient(create_app(load_settings(), Usecases(workspace=FakeWorkspace())))


def test_projects_endpoints() -> None:
    client = _client()

    resp = client.get("/api/projects")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["projects"][0]["sessions"] == 2

    resp = client.post("/api/projects", json={"name": "新田"})
    assert resp.json() == {"key": "manual:9", "name": "新田"}

    ok = client.post("/api/projects/bind",
                     json={"session_id": 1, "project_key": "card:abc"})
    assert ok.json()["bound"] is True
    bad = client.post("/api/projects/bind",
                      json={"session_id": 1, "project_key": "manual:999"})
    assert bad.status_code == 422


def test_search_notifications_skills_files_branch_endpoints() -> None:
    client = _client()

    assert client.get("/api/search", params={"q": "x"}).json()["cards"][0]["name"] == "x"
    assert client.get("/api/notifications").json()["completed_recently"] == 3
    assert client.get("/api/skills").json()["count"] == 1
    assert client.get("/api/files").json()["files"][0]["name"] == "x.md"
    assert client.get("/api/git/branch").json() == {"branch": "main"}


def test_plugins_endpoints() -> None:
    client = _client()

    body = client.get("/api/plugins").json()
    assert body["installed_count"] == 1
    by_id = {p["id"]: p for p in body["plugins"]}
    assert by_id["eval"]["enabled"] is True

    ok = client.post("/api/plugins/eval/toggle", json={"enabled": False})
    assert ok.json() == {"id": "eval", "enabled": False}

    # 通道类插件不给 toggle：提示去 config 配置
    resp = client.post("/api/plugins/smtp/toggle", json={"enabled": True})
    assert resp.status_code == 422

    assert client.post("/api/plugins/不存在/toggle",
                       json={"enabled": True}).status_code == 404


def test_access_endpoint(monkeypatch) -> None:
    import contest_agent.presentation.server as server_module

    called = []
    monkeypatch.setattr(server_module, "set_access_full",
                        lambda full: called.append(full))

    resp = _client().post("/api/config/access", json={"full": True})
    assert resp.json() == {"access_full": True}
    assert called == [True]


# ---------- M8：删除手动项目（解绑会话，会话保留） ----------


def test_delete_manual_project_unbinds_but_keeps_sessions(workspace) -> None:
    """删手动项目：行消失；其下会话回到未归类；会话本体还在。"""
    service, comps, sessions, _, projects, _ = workspace
    manual = service.create_project("待删项目")
    sessions.create_session("chat", "项目里的对话")
    assert service.bind_session(2, manual.key) is True

    unbound = service.delete_project(manual.key)
    assert unbound == 1
    assert all(p.key != manual.key for p in service.list_projects())
    # 会话本体保留、归属已清空
    remaining = sessions.list_sessions(limit=10)
    target = next(s for s in remaining if s.id == 2)
    assert target.project_key is None


def test_delete_card_project_rejected_and_missing_404(workspace) -> None:
    """比赛卡派生项目拒删（422 语义）；不存在的键报不存在。"""
    service, comps, *_ = workspace
    card_key = service.list_projects()[0].key  # auto 项目
    try:
        service.delete_project(card_key)
        raise AssertionError("应当拒绝删除比赛卡项目")
    except ValueError as error:
        assert "不能删除" in str(error)
    try:
        service.delete_project("manual:99999")
        raise AssertionError("应当报项目不存在")
    except ValueError as error:
        assert "不存在" in str(error)
