"""权限门（PermissionGate）：写类工具执行前可配置的"人工确认"（M3）。

背景（ADR-002 遗留的对照题）：AgentScope 自带权限系统，但 CLI 是
无人值守场景，v1.5 起我们给所有工具显式挂了 ALLOW（自动放行）。
M3 定时推送让"无人值守"成为常态，"要不要所有工具都无条件放行"
就成了一个真问题。

两个学派（开发文档 §12 的取舍题）：
- **沙箱学派**（pi 的选择）：不挑工具，把整个 agent 关进容器里跑，
  出了圈也砸不坏外面——适合 agent 手握 shell 这类"大权"时；
- **权限门学派**（本项目的选择）：工具都是我们自己写的、能力有界
  （存文件、搜索、读网页），按名单挑出敏感工具做人工确认/禁用即可。

当前没有 shell 类大权工具，权限门够用；哪天加了 shell 工具，
再上沙箱（两条路不冲突，权限门照旧做第一道闸）。

两个开关（config.yaml 的 permissions 段，都是空 = 现状全放行）：
- confirm_tools：**交互模式**下（终端有人），执行前列表里的工具前先问 y/N；
- unattended_deny_tools：**无人值守**时（cron/watch、HTTP 服务），
  列表里的工具一律拒绝，拒绝理由会回给模型让它换路走。

注意确认发生在 agent 循环内部（工具被调用时），input() 会阻塞
事件循环——交互 CLI 场景这正是想要的"停下来等人"。
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from functools import wraps


class PermissionGate:
    """配置驱动的工具权限门。所有方法都容忍"没配置"（空名单 = 全放行）。"""

    def __init__(
        self,
        confirm_tools: list[str] | tuple[str, ...] = (),
        unattended_deny_tools: list[str] | tuple[str, ...] = (),
        interactive: bool | None = None,
    ):
        self._confirm = set(confirm_tools)
        self._deny_unattended = set(unattended_deny_tools)
        if interactive is None:
            # 自动探测：stdin 连着终端 = 有人；cron/管道/服务 = 无人值守。
            # 测试可以直接传 True/False 跳过探测
            self._interactive = sys.stdin is not None and sys.stdin.isatty()
        else:
            self._interactive = interactive

    def wrap(self, func: Callable[..., str]) -> Callable[..., str]:
        """按配置给工具函数套上权限外壳；不在任何名单里就原样返回。

        套在外壳链的"截断壳之外、记录壳之内"：拒绝的结果也会被记进
        会话轨迹（回放时看得到模型被拦了），但不会真的执行到原函数。
        """
        name = getattr(func, "__name__", "tool")

        # 规则一：无人值守 + 明确禁用名单 → 一律拒绝
        if not self._interactive and name in self._deny_unattended:
            @wraps(func)
            def denied(*args, **kwargs):
                return (
                    f"被权限门拦截：{name} 在无人值守模式下被禁用"
                    f"（config.yaml permissions.unattended_deny_tools）。"
                    f"请改用其他方式完成任务，或向用户说明这一限制。"
                )
            return denied

        # 规则二：交互模式 + 确认名单 → 执行前问人
        if self._interactive and name in self._confirm:
            @wraps(func)
            def confirmable(*args, **kwargs):
                answer = input(
                    f"\n[权限门] 即将执行 {name}，允许这次调用吗？[y/N] "
                ).strip().lower()
                if answer == "y":
                    return func(*args, **kwargs)
                return (
                    f"你（用户）拒绝了本次 {name} 调用。"
                    f"请换别的方式完成任务，或直接向用户说明无法执行及原因。"
                )
            return confirmable

        return func
