"""skill 加载器：把"怎么干某类活"的指令外置成 Markdown 文件（P4）。

一个 skill = skills/<名字>.md，结构分两段：
    ---
    name: ppt-outline
    description: 一句话说明
    ---              <- 以上是 frontmatter（元信息），以下是正文（给模型的指令）
    （指令正文）

为什么外置成文件而不是写死在代码里？——和 P2 的提示词模块同理：
技能指令是改动最频繁的部分。新增一个技能 = 加一个 .md 文件，
代码零改动（这和 Claude Code 的 Skill 机制是同一个思想）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ...settings import PROJECT_ROOT

DEFAULT_SKILLS_DIR = PROJECT_ROOT / "skills"


@dataclass
class Skill:
    """一个已加载的技能。"""

    name: str
    description: str
    instructions: str  # 正文：给模型的分步指令和质量要求


def load_skill(name: str, skills_dir: Path | None = None) -> Skill:
    """按名字加载技能；不存在就报错并列出可用的，方便人纠错。"""
    directory = skills_dir or DEFAULT_SKILLS_DIR
    path = directory / f"{name}.md"
    if not path.exists():
        available = ", ".join(list_skills(directory)) or "（一个都没有）"
        raise FileNotFoundError(f"技能 {name!r} 不存在。可用的技能：{available}")

    text = path.read_text(encoding="utf-8")
    return _parse_skill_text(text, fallback_name=name)


def list_skills(skills_dir: Path | None = None) -> list[str]:
    """列出全部技能名（就是 skills/ 下的 .md 文件名，去掉后缀）。"""
    directory = skills_dir or DEFAULT_SKILLS_DIR
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.md"))


def _parse_skill_text(text: str, fallback_name: str) -> Skill:
    """把 skill 文本拆成 frontmatter（元信息）+ 正文（指令）两段。

    frontmatter 用 yaml 解析（pyyaml 本来就是项目依赖）；
    没有 frontmatter 的文件也能加载，name 退回文件名。
    """
    if text.startswith("---"):
        # frontmatter 夹在第一对 --- 之间
        _, front, body = text.split("---", 2)
        meta = yaml.safe_load(front) or {}
        return Skill(
            name=str(meta.get("name", fallback_name)),
            description=str(meta.get("description", "")),
            instructions=body.strip(),
        )
    return Skill(name=fallback_name, description="", instructions=text.strip())
