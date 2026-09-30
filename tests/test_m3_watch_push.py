"""M3 验收测试：定时推送、子代理（研究分身）、权限门。

分层手法沿前几篇：
- 推送通道用"本地 HTTP 服务器收包"测 webhook（真 HTTP 往返，但不碰外网）；
- watch 用例用假识别/假通道测编排（谁推了、谁挂了、结果怎么汇报）；
- 子代理工具用假搜索 + 假摘要模型测（分身调了几次、摘要有没有界）；
- 权限门用 monkeypatch 假 stdin 测交互确认与非交互拦截。
真实定时任务的验收（cron + 真通道）标了 live。
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from contest_agent.application.usecases.identify_competitions import (
    IdentifyCompetitions,
)
from contest_agent.application.usecases.watch_site import WatchSite, _format_digest
from contest_agent.domain.entities import Competition, Notice
from contest_agent.infrastructure.push.pushers import (
    FilePusher,
    SmtpMailer,
    WebhookPusher,
    build_pushers,
)
from contest_agent.settings import PushConfig, SmtpConfig


# ---------- 推送通道 ----------


def test_file_pusher_writes_markdown_files(tmp_path: Path) -> None:
    pusher = FilePusher(tmp_path)
    assert pusher.channel_name == "file"

    pusher.send("发现 1 场新比赛", "- 蓝桥杯")
    pusher.send("发现 1 场新比赛", "- 数媒竞赛")  # 同秒两次也不覆盖

    files = sorted(tmp_path.glob("*.md"))
    assert len(files) == 2
    text = files[0].read_text(encoding="utf-8")
    assert text.startswith("# 发现 1 场新比赛")
    assert "蓝桥杯" in text or "数媒竞赛" in text


class _CaptureHandler(BaseHTTPRequestHandler):
    """本地收包器：记下 POST 到来的 JSON，回 200（或指定状态码）。"""

    received: dict = {}
    status = 200

    def do_POST(self):  # noqa: N802（http.server 的命名约定）
        length = int(self.headers.get("content-length", 0))
        type(self).received = json.loads(self.rfile.read(length))
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *args):  # 静音请求日志
        pass


def test_webhook_pusher_posts_json_to_local_server() -> None:
    """webhook 通道：真 HTTP 往返（本地起服务器收包，不碰外网）。"""
    server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        pusher = WebhookPusher(f"http://127.0.0.1:{port}/hook", timeout=5)
        pusher.send("🔔 发现 2 场新比赛", "- 蓝桥杯\n- 数媒竞赛")

        assert _CaptureHandler.received["title"] == "🔔 发现 2 场新比赛"
        assert "蓝桥杯" in _CaptureHandler.received["content"]
    finally:
        server.shutdown()

    # 接收方拒收（非 2xx）必须抛异常——上层要知道这个通道挂了
    _CaptureHandler.status = 500
    server2 = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    threading.Thread(target=server2.serve_forever, daemon=True).start()
    try:
        bad = WebhookPusher(f"http://127.0.0.1:{server2.server_address[1]}/hook", timeout=5)
        with pytest.raises(Exception):
            bad.send("t", "c")
    finally:
        server2.shutdown()


def test_smtp_mailer_requires_password_env(monkeypatch) -> None:
    """邮件通道：密码没配要在发信前明确报错（报错里指明环境变量名）。"""
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    mailer = SmtpMailer(SmtpConfig(host="smtp.test.com", user="a@test.com",
                                   to_addrs=["b@test.com"]))
    assert mailer.channel_name == "smtp"
    with pytest.raises(RuntimeError, match="SMTP_PASSWORD"):
        mailer.send("t", "c")


def test_smtp_mailer_sends_via_ssl(monkeypatch) -> None:
    """邮件通道正常路径：用假 SMTP 服务器类验证登录与发信的调用序列。"""

    class FakeSMTP:
        calls: list = []

        def __init__(self, host, port) -> None:
            FakeSMTP.calls.append(("connect", host, port))

        def login(self, user, password) -> None:
            FakeSMTP.calls.append(("login", user, password))

        def sendmail(self, from_addr, to_addrs, body) -> None:
            FakeSMTP.calls.append(("send", from_addr, to_addrs))

        def quit(self) -> None:
            FakeSMTP.calls.append(("quit",))

    import contest_agent.infrastructure.push.pushers as pushers_module
    monkeypatch.setattr(pushers_module.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("SMTP_PASSWORD", "secret-code")

    mailer = SmtpMailer(SmtpConfig(host="smtp.test.com", port=465, user="a@test.com",
                                   to_addrs=["b@test.com"]))
    mailer.send("标题", "正文")

    kinds = [c[0] for c in FakeSMTP.calls]
    assert kinds == ["connect", "login", "send", "quit"]
    assert FakeSMTP.calls[1][1] == "a@test.com"


def test_build_pushers_follows_config() -> None:
    """配置了哪个通道就造哪个，全不配 = 空列表（只识别不外推）。"""
    assert build_pushers(PushConfig()) == []
    pushers = build_pushers(PushConfig(
        webhook_url="http://x/hook", file_dir="/tmp/notes",
        smtp=SmtpConfig(host="h", user="a@x", to_addrs=["b@x"]),
    ))
    assert [p.channel_name for p in pushers] == ["webhook", "file", "smtp"]


# ---------- watch 用例 ----------


class FakePusher:
    """假通道：记录收到的内容；可指定炸不炸（测单通道故障不拖累其他通道）。"""

    def __init__(self, name: str, boom: bool = False) -> None:
        self._name = name
        self._boom = boom
        self.sent: list[tuple[str, str]] = []

    @property
    def channel_name(self) -> str:
        return self._name

    def send(self, title: str, content: str) -> None:
        if self._boom:
            raise ConnectionError("模拟通道故障")
        self.sent.append((title, content))


def _identify_with_store(saved_flags: list[bool]) -> tuple[IdentifyCompetitions, object]:
    """造一个识别用例 + 假卡片仓储：save_if_absent 按脚本依次返回 True/False。"""

    class FakeLlm:
        def complete_structured(self, system, user, schema):
            return {"is_competition": True, "name": "测试杯", "type": "exam",
                    "deadline": "2027-01-01", "reason": "是比赛"}

    class FakeSource:
        def list_notices(self, limit=10):
            return [Notice(source_url=f"u{i}", title=f"测试杯{i}报名通知")
                    for i in range(len(saved_flags))]

        def fetch_detail(self, notice):
            notice.content = "竞赛报名正文"
            return notice

    class FakeStore:
        def __init__(self) -> None:
            self.flags = list(saved_flags)
            self.saved: list[Competition] = []

        def save_if_absent(self, competition) -> bool:
            self.saved.append(competition)
            return self.flags.pop(0)

        def list_all(self):
            return self.saved

    store = FakeStore()
    return IdentifyCompetitions(FakeSource(), FakeLlm(), store), store


def test_watch_pushes_only_new_cards() -> None:
    """首次盯梢（两张新卡）推给两个通道；第二次（全部已存在）不推。"""
    identify, store = _identify_with_store([True, True])
    web = FakePusher("webhook")
    filep = FakePusher("file")
    watch = WatchSite(identify, pushers=[web, filep])

    result = watch.execute(limit=2, push=True)

    assert len(result.new_cards) == 2
    assert len(web.sent) == 1 and len(filep.sent) == 1
    title, content = web.sent[0]
    assert "2 场新比赛" in title
    # 内容里是两张卡片的名字（假 LLM 都叫"测试杯"）和各自的通知网址
    assert content.count("测试杯") == 2
    assert "u0" in content and "u1" in content
    assert "2027-01-01" in content
    assert all(r["ok"] for r in result.push_results)

    # 第二次：卡片已存在（save_if_absent 返回 False），没有新面孔不推送
    store.flags = [False, False]
    result2 = watch.execute(limit=2, push=True)
    assert result2.new_cards == []
    assert result2.push_results == []
    assert len(web.sent) == 1        # 通道没被打扰


def test_watch_one_broken_channel_does_not_block_others() -> None:
    """webhook 挂了，file 照发；失败结果如实汇报（降级原则）。"""
    identify, _ = _identify_with_store([True])
    web = FakePusher("webhook", boom=True)
    filep = FakePusher("file")
    watch = WatchSite(identify, pushers=[web, filep])

    result = watch.execute(limit=1, push=True)

    assert len(filep.sent) == 1                      # 别的通道照常送达
    by_channel = {r["channel"]: r for r in result.push_results}
    assert by_channel["webhook"]["ok"] is False
    assert "模拟通道故障" in by_channel["webhook"]["error"]
    assert by_channel["file"]["ok"] is True


def test_watch_dry_run_skips_push() -> None:
    """--no-push 干跑：新卡照常识别出来，但通道一个都不被打扰。"""
    identify, _ = _identify_with_store([True])
    web = FakePusher("webhook")
    watch = WatchSite(identify, pushers=[web])

    result = watch.execute(limit=1, push=False)

    assert len(result.new_cards) == 1
    assert result.push_results == []
    assert web.sent == []


def test_format_digest_contains_name_type_deadline_url() -> None:
    cards = [Competition(name="蓝桥杯", notice_url="http://x/1", type="exam",
                         deadline=None)]
    title, content = _format_digest(cards)
    assert "蓝桥杯" in content and "见通知" in content and "http://x/1" in content
