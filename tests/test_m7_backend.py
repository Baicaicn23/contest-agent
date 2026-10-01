"""M7 后端验收测试：右侧工具坞（文件树 /api/tree、终端 /api/terminal）。

- WorkspaceService 用真 SQLite 内存库 + 临时目录 + 假回调（终端用假 runner）；
- HTTP 端点用 create_app + 假用例，验证装配检查/路径安全/空命令；
- 顺带回归 /api/files/content 的子目录预览（M7 修复：之前只许纯文件名）。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contest_agent.application.usecases.workspace import WorkspaceService
from contest_agent.presentation.server import Usecases, create_app
from contest_agent.settings import load_settings


# ---------- WorkspaceService：文件树与终端（假 runner） ----------


@pytest.fixture
def tree_workspace(tmp_path: Path):
    """带临时 output/ 目录的 workspace：目录里摆好 子目录/文件/隐藏文件。"""
    output = tmp_path / "output"
    (output / "notifications").mkdir(parents=True)
    (output / "ppt-outline.pptx").write_bytes(b"\x00\x01")
    (output / "report.md").write_text("# 报告", encoding="utf-8")
    (output / "notifications" / "a.md").write_text("通知A", encoding="utf-8")
    (output / ".DS_Store").write_bytes(b"\x00")

    def fake_runner(command: str) -> dict:
        return {"command": command, "exit_code": 0, "output": f"ran:{command}",
                "duration_ms": 1}

    service = _make_workspace(tmp_path, output, fake_runner)
    return service, output


def _make_workspace(tmp_path: Path, output: Path, runner) -> WorkspaceService:
    return WorkspaceService(
        competition_repository=None,
        session_archive=None,
        notice_repository=None,
        project_store=None,
        usage_repository=None,
        memory=None,
        skills_dir=tmp_path / "skills",
        output_dir=output,
        git_runner=lambda: "main",
        command_runner=runner,
    )


def test_file_tree_shape_and_order(tree_workspace) -> None:
    """树：目录在前、文件按名排序、隐藏文件跳过、文件带 size。"""
    service, _ = tree_workspace
    tree = service.file_tree()
    assert tree["root"] == "output"
    names = [n["name"] for n in tree["children"]]
    # notifications（目录）在最前；.DS_Store 被跳过
    assert names == ["notifications", "ppt-outline.pptx", "report.md"]
    subdir = tree["children"][0]
    assert subdir["type"] == "dir" and subdir["children"][0]["name"] == "a.md"
    file_node = tree["children"][2]
    assert file_node["type"] == "file" and file_node["size"] == 8  # "# 报告" utf-8 = 1+1+3+3 字节


def test_file_tree_missing_dir(tmp_path: Path) -> None:
    """output/ 不存在时返回空树而不是炸。"""
    service = _make_workspace(tmp_path, tmp_path / "nope", lambda c: {})
    assert service.file_tree() == {"root": "output", "children": []}


def test_run_terminal_dispatch_and_guards(tmp_path: Path) -> None:
    """run_terminal 走注入回调；空命令拒绝；没配 runner 拒绝。"""
    service = _make_workspace(tmp_path, tmp_path / "out",
                              lambda c: {"command": c, "exit_code": 0, "output": "ok"})
    assert service.run_terminal(" echo hi ")["command"] == "echo hi"  # 去空白
    with pytest.raises(ValueError):
        service.run_terminal("   ")
    bare = WorkspaceService(
        competition_repository=None, session_archive=None, notice_repository=None,
        project_store=None, usage_repository=None, memory=None,
        skills_dir=tmp_path, output_dir=tmp_path, git_runner=lambda: "main",
    )
    with pytest.raises(RuntimeError):
        bare.run_terminal("ls")


# ---------- HTTP 端点（假用例） ----------


@pytest.fixture
def client(tmp_path: Path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "notifications").mkdir()
    (output / "notifications" / "n.md").write_text("通知正文", encoding="utf-8")
    (output / "top.md").write_text("顶层文件", encoding="utf-8")

    def runner(command: str) -> dict:
        return {"command": command, "exit_code": 0, "output": "done", "duration_ms": 2}

    service = _make_workspace(tmp_path, output, runner)
    app = create_app(load_settings(), Usecases(workspace=service))
    return TestClient(app), output


def test_api_tree_endpoint(client) -> None:
    """GET /api/tree 返回树形 JSON。"""
    tc, _ = client
    resp = tc.get("/api/tree")
    assert resp.status_code == 200
    body = resp.json()
    assert body["root"] == "output"
    assert {n["name"] for n in body["children"]} == {"notifications", "top.md"}


def test_api_terminal_endpoint_and_validation(client) -> None:
    """POST /api/terminal 正常执行；空命令 422。"""
    tc, _ = client
    ok = tc.post("/api/terminal", json={"command": "echo hello"})
    assert ok.status_code == 200
    assert ok.json()["exit_code"] == 0 and ok.json()["output"] == "done"
    assert tc.post("/api/terminal", json={"command": "  "}).status_code == 422


def test_api_file_content_subdir_allowed_traversal_blocked(client) -> None:
    """预览：子目录文件可读（M7 修复）；.. 穿越与绝对路径仍被拒。"""
    tc, _ = client
    ok = tc.get("/api/files/content", params={"name": "notifications/n.md"})
    assert ok.status_code == 200 and "通知正文" in ok.json()["content"]
    assert tc.get("/api/files/content",
                  params={"name": "../settings.py"}).status_code == 422
    assert tc.get("/api/files/content",
                  params={"name": "/etc/passwd"}).status_code == 422
