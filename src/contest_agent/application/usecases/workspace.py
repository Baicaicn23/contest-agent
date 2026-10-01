"""workspace 用例：Codex 式工作台面板的数据与操作（M5）。

一个用例聚齐"界面外壳"需要的七类数据，全部来自真实系统：
    项目列表（比赛卡自动派生 + 手动新建）｜全局搜索（会话/卡片/通知）
    通知（紧急截止数 + 近期完成）｜技能清单（skills/ 目录 frontmatter）
    output 文件列表（右侧工具面板）｜git 分支（composer 的 main chip）
    插件注册表（能力开关，安装状态来自 config）

依赖注入说明：比赛/会话/通知走领域端口；skills 目录、output 目录、
git 命令这些"环境细节"由装配根以 Path / 回调注入——application 层
保持不碰文件系统与子进程。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from ...domain.entities import Competition, ProjectInfo
from ...domain.ports import (
    CompetitionRepositoryPort,
    MemoryPort,
    NoticeRepositoryPort,
    ProjectStorePort,
    SessionArchivePort,
    UsageRepositoryPort,
)

# 插件注册表：id → 展示信息 + 对应的 features/config 开关键。
# enabled 的判定分两类：features 键（布尔开关）与"配置存在即开启"（通道类）。
PLUGIN_REGISTRY: list[dict] = [
    {"id": "deadlines", "name": "截止守望", "desc": "T-7/3/1/0 四档倒计时警报",
     "category": "情报", "kind": "feature", "key": "deadlines"},
    {"id": "watch", "name": "定时盯梢", "desc": "cron 哨兵扫官网推新比赛",
     "category": "情报", "kind": "feature", "key": "watch"},
    {"id": "eval", "name": "识别评测", "desc": "31 条真实考卷防退化",
     "category": "治理", "kind": "feature", "key": "eval"},
    {"id": "pptx", "name": "PPT 导出", "desc": "生成材料导出 .pptx 文件",
     "category": "产出", "kind": "feature", "key": "pptx"},
    {"id": "webhook", "name": "Webhook 推送", "desc": "推送接口（钉钉/企微/Server酱）",
     "category": "推送", "kind": "push", "key": "webhook"},
    {"id": "smtp", "name": "邮件推送", "desc": "SMTP 邮件通知（需授权码）",
     "category": "推送", "kind": "push", "key": "smtp"},
    {"id": "file", "name": "文件落盘", "desc": "通知写 Markdown 到本地目录",
     "category": "推送", "kind": "push", "key": "file"},
]


class WorkspaceService:
    """工作台面板的数据与操作。"""

    def __init__(
        self,
        competition_repository: CompetitionRepositoryPort,
        session_archive: SessionArchivePort,
        notice_repository: NoticeRepositoryPort,
        project_store: ProjectStorePort,
        usage_repository: UsageRepositoryPort,
        memory: MemoryPort,
        skills_dir: Path,
        output_dir: Path,
        git_runner: Callable[[], str],
        command_runner: "Callable[[str], dict] | None" = None,
    ):
        self.competitions = competition_repository
        self.sessions = session_archive
        self.notices = notice_repository
        self.projects = project_store
        self.usage = usage_repository
        self.memory = memory
        self.skills_dir = skills_dir
        self.output_dir = output_dir
        self.git_runner = git_runner
        # 终端执行回调（M7 右侧工具坞）：同样由装配根注入，本层不碰 subprocess。
        # None = 装配根没给（测试场景），run_terminal 会拒绝执行。
        self.command_runner = command_runner

    # ---------- 项目 ----------

    def list_projects(self) -> list[ProjectInfo]:
        """项目列表：比赛卡自动派生 + 手动新建，按会话归属计数。"""
        result: list[ProjectInfo] = []
        session_counts: dict[str, int] = {}
        for s in self.sessions.list_sessions(limit=200):
            if s.project_key:
                session_counts[s.project_key] = session_counts.get(s.project_key, 0) + 1

        cards: list[Competition] = self.competitions.list_all()
        seen = set()
        for card in cards:
            key = _card_key(card)
            seen.add(key)
            result.append(ProjectInfo(
                key=key, name=card.name, source="auto",
                deadline=card.deadline,
                sessions=session_counts.get(key, 0),
            ))
        for manual in self.projects.list_manual():
            if manual.key not in seen:
                manual.sessions = session_counts.get(manual.key, 0)
                result.append(manual)
        return result

    def create_project(self, name: str) -> ProjectInfo:
        """手动新建项目（名字必填，去空白）。"""
        name = (name or "").strip()
        if not name:
            raise ValueError("项目名不能为空")
        pid = self.projects.create(name)
        return ProjectInfo(key=f"manual:{pid}", name=name, source="manual")

    def bind_session(self, session_id: int, project_key: str) -> bool:
        """把会话归属到项目。项目键必须是真实存在的项目。"""
        valid = {p.key for p in self.list_projects()}
        if project_key not in valid:
            raise ValueError(f"项目 {project_key!r} 不存在")
        return self.sessions.bind_session(session_id, project_key)

    def delete_project(self, project_key: str) -> int:
        """删除手动项目（M8 侧栏垃圾桶），返回解绑的会话数。

        比赛卡派生项目（card:*）不可删——它们由卡片数据现算，删了下次
        列表还会出现，删等于骗人；手动项目删除只解除会话归属，
        会话本体（轨迹/台账）一律保留。
        """
        if not project_key.startswith("manual:"):
            raise ValueError("比赛卡派生的项目不能删除（由比赛数据自动维护）")
        if self.projects.delete(project_key) is False:
            raise ValueError(f"项目 {project_key!r} 不存在")
        return self.sessions.unbind_project(project_key)

    # ---------- 全局搜索 ----------

    def search(self, query: str) -> dict:
        """跨 会话备注 / 比赛卡片名 / 通知标题 的模糊搜索（大小写不敏感）。"""
        q = (query or "").strip().lower()
        if not q:
            return {"sessions": [], "cards": [], "notices": []}

        session_hits = [
            {"id": s.id, "title": f"{s.task_type} · {s.note or s.id}", "status": s.status}
            for s in self.sessions.list_sessions(limit=200)
            if q in (s.note or "").lower() or q in s.task_type.lower()
        ]
        card_hits = [
            {"name": c.name, "url": c.notice_url, "type": c.type}
            for c in self.competitions.list_all()
            if q in c.name.lower()
        ]
        notice_hits = [
            {"title": n.title, "url": n.source_url}
            for n in self.notices.list_notices()
            if q in n.title.lower()
        ]
        # 各限 8 条，防一屏爆
        return {"sessions": session_hits[:8], "cards": card_hits[:8],
                "notices": notice_hits[:8]}

    # ---------- 通知与技能/文件/git ----------

    def notifications(self) -> dict:
        """铃铛下拉的数据：紧急截止（≤1 天）+ 近 24h 完成的任务数。"""
        urgent = [
            a for a in self.deadline_upcoming()
            if a.remaining <= 1
        ]
        recent_done = sum(
            1 for s in self.sessions.list_sessions(limit=50)
            if s.status == "completed"
            and s.ended_at is not None
        )
        return {
            "urgent_deadlines": [
                {"name": a.card.name, "label": a.label, "remaining": a.remaining}
                for a in urgent
            ],
            "completed_recently": recent_done,
        }

    def deadline_upcoming(self, within_days: int = 30):
        """临近截止列表（供 notifications 与 deadlines 视图复用）。

        这里不直接依赖哨兵（避免循环依赖），自己按剩余天数过滤；
        label 复用哨兵的人话函数，保证两处口径一致。
        """
        from .deadline_watch import _label

        today = date_today()
        out = []
        for card in self.competitions.list_all():
            if card.deadline is None:
                continue
            day = card.deadline.date() if hasattr(card.deadline, "date") else card.deadline
            remaining = (day - today).days
            if 0 <= remaining <= within_days:
                out.append(type("A", (), {
                    "card": card, "remaining": remaining, "label": _label(remaining),
                })())
        out.sort(key=lambda a: a.remaining)
        return out

    def list_skills(self) -> list[dict]:
        """解析 skills/ 目录的 frontmatter（名称 + 描述）。"""
        skills = []
        if not self.skills_dir.is_dir():
            return skills
        for path in sorted(self.skills_dir.glob("*.md")):
            name, desc = path.stem, ""
            head = path.read_text(encoding="utf-8")[:600]
            for line in head.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()
            skills.append({"file": path.name, "name": name, "description": desc})
        return skills

    def list_files(self) -> list[dict]:
        """output/ 目录的文件清单（工具面板用），按修改时间倒序。"""
        if not self.output_dir.is_dir():
            return []
        entries = []
        for path in self.output_dir.rglob("*"):
            if path.is_file():
                stat = path.stat()
                entries.append({
                    "name": path.relative_to(self.output_dir).as_posix(),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                })
        entries.sort(key=lambda e: e["modified"], reverse=True)
        return entries[:50]

    def file_tree(self, max_depth: int = 6) -> dict:
        """output/ 目录的树形结构（M7 右侧文件树用）。

        目录排前面、同层按名排序；隐藏文件（.开头）直接跳过；
        限深 6 层——防符号链接成环或异常深的目录把请求拖死。
        """
        if not self.output_dir.is_dir():
            return {"root": "output", "children": []}
        return {
            "root": self.output_dir.name,
            "children": self._walk_dir(self.output_dir, depth=0, max_depth=max_depth),
        }

    def _walk_dir(self, directory: Path, depth: int, max_depth: int) -> list[dict]:
        """递归一层目录 → 节点列表。目录节点 {"type":"dir","children":[...]}，
        文件节点 {"type":"file","size":字节数}。"""
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda p: (p.is_file(), p.name.lower()),  # 目录在前（False<True）
            )
        except OSError:
            return []  # 无权限/已消失的目录：安静地当作空目录
        nodes: list[dict] = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                nodes.append({
                    "name": entry.name,
                    "type": "dir",
                    "children": (
                        self._walk_dir(entry, depth + 1, max_depth)
                        if depth + 1 < max_depth else []
                    ),
                })
            elif entry.is_file():
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                nodes.append({"name": entry.name, "type": "file", "size": size})
        return nodes

    def run_terminal(self, command: str) -> dict:
        """在项目根目录执行一条 shell 命令（M7 终端面板）。

        执行细节全部在装配根注入的 command_runner 里（超时/截断在那边）；
        这里只做两件事：没配 runner 就拒绝、空命令拒绝。
        """
        command = (command or "").strip()
        if not command:
            raise ValueError("命令不能为空")
        if self.command_runner is None:
            raise RuntimeError("终端执行未装配")
        return self.command_runner(command)

    def git_branch(self) -> str:
        """当前 git 分支（composer 的分支 chip）。失败返回 'main' 兜底。"""
        try:
            return self.git_runner().strip() or "main"
        except Exception:
            return "main"

    # ---------- 插件 ----------

    def plugins_status(self, yaml_config) -> list[dict]:
        """插件清单 + 安装状态（安装状态全部读自 config，绝不存第二份）。"""
        out = []
        for plugin in PLUGIN_REGISTRY:
            if plugin["kind"] == "feature":
                enabled = bool(yaml_config.features.get(plugin["key"], True))
            else:
                push = yaml_config.push
                enabled = {
                    "webhook": push.webhook_url is not None,
                    "smtp": push.smtp is not None,
                    "file": bool(push.file_dir),
                }[plugin["key"]]
            out.append({**plugin, "enabled": enabled,
                        "toggleable": plugin["kind"] == "feature"})
        return out


def _card_key(card: Competition) -> str:
    """比赛卡 → 项目键（与 repository.competition_hash 同源：URL+名称）。"""
    import hashlib

    raw = f"{card.notice_url}|{card.name}"
    return "card:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def date_today():
    """今天的日期（独立小函数：测试可 monkeypatch）。"""
    return date.today()
