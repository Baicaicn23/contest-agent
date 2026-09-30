"""推送通道的三个实现（M3 定时推送）：webhook / 邮件 / 本地文件。

都实现 domain/ports.py 的 PushPort（能力九）。挑哪个由 config.yaml 决定，
配了哪个就启用哪个，可以同时启用多个——业务层（watch 用例）只认端口，
对通道一无所知。这是"依赖倒置"的又一次照抄 v1 的套路：
换/加推送方式 = 装配根里换一个类，业务一行不动。

设计共识（三个实现都遵守）：
- 失败抛异常，不吞——"哪个通道挂了"由 watch 用例统一兜住并播报，
  因为它才知道怎么降级（换下一个通道、继续下一次定时任务）；
- 内容是纯文本/Markdown，不搞各通道的花式格式（机器人自己的
  markdown 方言由接收端自行渲染，实在不渲染也不影响阅读）。
"""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

import requests

from ...settings import PushConfig, SmtpConfig


class WebhookPusher:
    """webhook 通道：往配置的 URL POST 一段 JSON。

    这是钉钉/企业微信/Server酱等"机器人"的通用形态——它们都暴露一个
    URL，POST 什么就展示什么。想在哪个平台收通知，把它的机器人
    webhook 地址填进 config.yaml 即可，本项目不做各平台的私有协议适配。
    """

    def __init__(self, url: str, timeout: float = 10):
        self._url = url
        self._timeout = timeout

    @property
    def channel_name(self) -> str:
        return "webhook"

    def send(self, title: str, content: str) -> None:
        resp = requests.post(
            self._url,
            json={"title": title, "content": content},
            timeout=self._timeout,
        )
        # 非 2xx 一律算失败（接收方拒收/限流），让上层知道并播报
        resp.raise_for_status()


class FilePusher:
    """本地文件通道：把通知写成一个 Markdown 文件。

    看似"自己推给自己"，但在两类场景里最实用：
    - 开发调试：不想配任何外部服务，就能跑通整个推送链路；
    - cron 无人值守：通知落成文件，配合 git/网盘就是一份推送历史存档。
    文件名带时间戳，多次推送不会互相覆盖。
    """

    def __init__(self, directory: str | Path):
        self._dir = Path(directory)

    @property
    def channel_name(self) -> str:
        return "file"

    def send(self, title: str, content: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        # 文件名里的标题只留安全字符（斜杠冒号在文件名里都是坑）
        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:40]
        path = self._dir / f"{stamp}-{safe_title}.md"
        # 同一秒推两次会撞名：已存在就追加序号 -2、-3……保证不覆盖
        serial = 2
        while path.exists():
            path = self._dir / f"{stamp}-{safe_title}-{serial}.md"
            serial += 1
        path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")


class SmtpMailer:
    """邮件通道：用标准库 smtplib 发一封纯文本邮件。

    配置里的密码只存"环境变量名"（和模型密钥同一套规矩）——
    真实授权码只在运行时从环境变量取，绝不进配置文件、不进 git。
    """

    def __init__(self, config: SmtpConfig):
        self._config = config

    @property
    def channel_name(self) -> str:
        return "smtp"

    def send(self, title: str, content: str) -> None:
        password = os.environ.get(self._config.password_env)
        if not password:
            raise RuntimeError(
                f"邮件推送缺密码：请设置环境变量 {self._config.password_env}"
                f"（邮箱 SMTP 授权码，不是登录密码）"
            )
        from_addr = self._config.from_addr or self._config.user
        message = MIMEText(content, "plain", "utf-8")
        message["Subject"] = title
        message["From"] = formataddr(("contest-agent", from_addr))
        message["To"] = ", ".join(self._config.to_addrs)

        # 465 端口走 SSL 直连；其他端口按 STARTTLS 明文升级处理（国内邮箱两种都常见）
        if self._config.port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(self._config.host, self._config.port)
        else:
            server = smtplib.SMTP(self._config.host, self._config.port)
            server.starttls()
        try:
            server.login(self._config.user, password)
            server.sendmail(from_addr, self._config.to_addrs, message.as_string())
        finally:
            server.quit()


def build_pushers(config: PushConfig) -> list:
    """按配置造出所有启用的推送通道（装配根用；一个都没配就返回空列表）。"""
    pushers = []
    if config.webhook_url:
        pushers.append(WebhookPusher(config.webhook_url, config.webhook_timeout))
    if config.file_dir:
        pushers.append(FilePusher(config.file_dir))
    if config.smtp:
        pushers.append(SmtpMailer(config.smtp))
    return pushers
