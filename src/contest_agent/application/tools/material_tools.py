"""材料生成工具集：agent 在生成材料时可以用的三件工具（P4）。

工具只提供"事实与动作"，怎么用由模型决定：
- list_competitions：库里有哪些比赛（事实）；
- get_notice_content：读某条通知的原文（事实）；
- save_material：把写好的材料落盘（动作）。

这个文件是"构建器"而不是直接 new：因为三个工具都依赖外部能力
（爬虫、仓储、输出目录），由 composition.py 把依赖递进来再组装。
"""

from __future__ import annotations

from pathlib import Path

from ...domain.ports import CompetitionRepositoryPort, NoticeSourcePort
from ..harness.registry import Tool, ToolRegistry

# 发给模型的正文上限：通知全文可能很长，模型不需要逐字看完全文
MAX_NOTICE_CHARS = 4000


def build_material_tools(
    source: NoticeSourcePort,
    competition_repository: CompetitionRepositoryPort,
    output_dir: Path,
) -> ToolRegistry:
    """把三件工具组装进一个工具箱。依赖全部由参数注入。"""
    registry = ToolRegistry()

    def list_competitions() -> str:
        """列出库里全部比赛卡片，一行一张。"""
        cards = competition_repository.list_all()
        if not cards:
            return "库里还没有比赛卡片。请先运行 sai identify 识别比赛。"
        lines = []
        for index, card in enumerate(cards, start=1):
            deadline = card.deadline.strftime("%Y-%m-%d") if card.deadline else "未写"
            lines.append(
                f"{index}. {card.name}（{card.type}，截止 {deadline}）"
                f" 通知：{card.notice_url}"
            )
        return "\n".join(lines)

    def get_notice_content(notice_url: str) -> str:
        """读取一条通知的正文文本（现场抓取详情页）。"""
        from ...domain.entities import Notice  # 函数内 import：只在用到时加载

        notice = source.fetch_detail(Notice(source_url=notice_url, title=""))
        if not notice.content:
            return "这条通知没有抓到正文（可能是图片/外链形式）。"
        return notice.content[:MAX_NOTICE_CHARS]

    def save_material(filename: str, content: str) -> str:
        """把材料保存为 Markdown 文件（只能存进输出目录，文件名只能是一层）。"""
        # 安全检查一：只允许纯文件名，不许带路径（防 ../ 目录穿越）
        if Path(filename).name != filename:
            return f"保存失败：文件名 {filename!r} 不能包含路径，只写文件名如 'ppt-outline.md'。"
        # 安全检查二：只允许 Markdown 文件，材料的格式保持统一
        if not filename.endswith(".md"):
            return "保存失败：文件必须以 .md 结尾。"

        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / filename
        target.write_text(content, encoding="utf-8")
        return f"已保存：{target}（{len(content)} 字）"

    registry.register(
        Tool(
            name="list_competitions",
            description="列出数据库里全部比赛卡片（名称/类型/截止日期/通知链接）",
            parameters={"type": "object", "properties": {}, "required": []},
            func=list_competitions,
        )
    )
    registry.register(
        Tool(
            name="get_notice_content",
            description="读取一条比赛通知的正文原文。参数 notice_url 填通知的完整网址",
            parameters={
                "type": "object",
                "properties": {
                    "notice_url": {
                        "type": "string",
                        "description": "通知详情页的完整 URL",
                    }
                },
                "required": ["notice_url"],
            },
            func=get_notice_content,
        )
    )
    registry.register(
        Tool(
            name="save_material",
            description="把写好的材料保存为 Markdown 文件。filename 如 'ppt-outline.md'，content 是全文",
            parameters={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "保存的文件名（仅文件名，不含路径）",
                    },
                    "content": {
                        "type": "string",
                        "description": "材料的完整 Markdown 全文",
                    },
                },
                "required": ["filename", "content"],
            },
            func=save_material,
        )
    )
    return registry
