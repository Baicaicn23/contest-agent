"""M9 后端验收测试：三档权限模式 + 上传端点 + 会话上下文 token 汇总。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contest_agent.application.harness.permission_gate import WRITE_TOOL_NAMES, PermissionGate
from contest_agent.presentation.server import Usecases, create_app
from contest_agent.settings import load_settings, set_permission_mode


# ---------- PermissionGate 三档 ----------


def _write_tool():
    def scan_latest_notices(limit: int = 1) -> str:
        return "扫到了"
    return scan_latest_notices


def _read_tool():
    def list_competitions() -> str:
        return "卡片"
    return list_competitions


def test_gate_readonly_blocks_write_passes_read() -> None:
    """只读档：写类工具被拒（理由回给模型）、读类工具照常。"""
    gate = PermissionGate(permission_mode="readonly", interactive=True)
    blocked = gate.wrap(_write_tool())
    assert "只读" in blocked() and "scan_latest_notices" in blocked()
    assert gate.wrap(_read_tool())() == "卡片"


def test_gate_full_overrides_and_confirm_blocks_unattended() -> None:
    """完全访问档全放行；confirm 档在无人值守（HTTP 聊天）拦下写工具并说明原因。"""
    full = PermissionGate(permission_mode="full", interactive=True)
    assert full.wrap(_write_tool())() == "扫到了"
    confirm = PermissionGate(permission_mode="confirm", interactive=False,
                             block_unattended_writes=True)
    out = confirm.wrap(_write_tool())()
    assert "变更前确认" in out and "无人值守" in out
    # 不带该标记（cron/CLI 场景）：保持 M3 语义，写工具不受 confirm 档影响
    cron = PermissionGate(permission_mode="confirm", interactive=False)
    assert cron.wrap(_write_tool())() == "扫到了"
    # 名单完整性：三个写类工具都在名单里
    assert {"scan_latest_notices", "identify_latest_notices", "save_material"} <= set(WRITE_TOOL_NAMES)


def test_set_permission_mode_roundtrip(tmp_path: Path) -> None:
    """行级写入：mode 落盘、full 档同步 access_full、非法值拒绝。"""
    config = tmp_path / "config.yaml"
    config.write_text(
        "permissions:\n"
        "  permission_mode: confirm\n"
        "  confirm_tools: []\n"
        "  unattended_deny_tools: []\n"
        "access_full: false\n",
        encoding="utf-8",
    )
    set_permission_mode("readonly", config)
    text = config.read_text(encoding="utf-8")
    assert "permission_mode: readonly" in text and "access_full: false" in text

    set_permission_mode("full", config)
    text = config.read_text(encoding="utf-8")
    assert "permission_mode: full" in text and "access_full: true" in text

    with pytest.raises(ValueError):
        set_permission_mode("yolo", config)


# ---------- HTTP：permission-mode 端点 / 上传 / sessions prompt_tokens ----------


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # 隔离：上传别写进真项目
    app = create_app(load_settings(), Usecases())
    return TestClient(app)


def test_permission_mode_endpoint_roundtrip(client) -> None:
    """POST /api/config/permission-mode 写入并回读（用真项目 config，
    测完还原，保证其他测试看到的状态不变）。"""
    resp = client.post("/api/config/permission-mode", json={"mode": "readonly"})
    assert resp.status_code == 200
    assert client.get("/api/config").json()["permission_mode"] == "readonly"
    # 还原为 confirm，避免污染其他用例
    assert client.post("/api/config/permission-mode", json={"mode": "confirm"}).status_code == 200
    assert client.post("/api/config/permission-mode", json={"mode": "yolo"}).status_code == 422


def test_upload_endpoint_saves_and_sanitizes(client, tmp_path: Path) -> None:
    """上传：真实落盘 output/uploads/；路径穿越文件名被清洗。
    端点写死项目根（绝对路径），测试后清理自己产生的文件。"""
    from contest_agent.presentation.server import PROJECT_ROOT

    uploaded = []
    try:
        r1 = client.post("/api/upload", files={"file": ("m9-test.txt", b"hello")})
        assert r1.status_code == 200
        body = r1.json()
        assert body["name"].startswith("uploads/") and body["size"] == 5
        uploaded.append(PROJECT_ROOT / "output" / body["name"])
        r2 = client.post("/api/upload", files={"file": ("../evil.txt", b"x")})
        assert r2.status_code == 200
        assert ".." not in r2.json()["name"]   # 只留文件名部分
        uploaded.append(PROJECT_ROOT / "output" / r2.json()["name"])
    finally:
        for path in uploaded:
            path.unlink(missing_ok=True)


# ---------- M10：read_attachment 工具（agent 读用户上传的附件） ----------


def test_read_attachment_text_and_traversal(tmp_path: Path) -> None:
    """文本附件直接读；穿越文件名只取文件名部分；找不到时列出现有文件。"""
    from contest_agent.application.harness.agent_factory import _make_read_attachment

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "要求.md").write_text("# 比赛要求\n提交 PPT 十页内", encoding="utf-8")
    trace = []
    tool = _make_read_attachment(uploads, trace)

    out = tool("要求.md")
    assert "比赛要求" in out and "PPT" in out
    assert trace == ["read_attachment(要求.md)"]

    # ../settings.py → 只取 settings.py，找不到并列出现有文件
    out2 = tool("../settings.py")
    assert "找不到附件" in out2 and "要求.md" in out2
    assert "contest_agent" not in out2   # 没把项目外文件内容带出来


def test_read_attachment_office_unsupported_and_pdf(tmp_path: Path) -> None:
    """Office 文档诚实告知不支持；PDF 走 pypdf 提取（用最小 PDF 验证链路）。"""
    from contest_agent.application.harness.agent_factory import _make_read_attachment

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "说明.docx").write_bytes(b"fake")
    tool = _make_read_attachment(uploads, [])
    assert "Office" in tool("说明.docx") and "PDF" in tool("说明.docx")

    # 用 pypdf 生成一个合法 PDF（含文本外观流），再走工具读出来
    import io

    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject, DictionaryObject, NameObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=100)
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 20 50 Td (hello attachment) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
    })
    buf = io.BytesIO()
    writer.write(buf)
    (uploads / "hello.pdf").write_bytes(buf.getvalue())

    out = tool("hello.pdf")
    assert "hello attachment" in out

    # uploads_dir 未配置（None）：不炸，给可读提示
    none_tool = _make_read_attachment(None, [])
    assert "重新上传" in none_tool("x.txt")
