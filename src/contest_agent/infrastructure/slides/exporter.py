"""slides 导出器：PPT 大纲 Markdown → .pptx 真实文件（M4 收尾）。

放在 infrastructure 的理由：它是"LLM 端口 + python-pptx 渲染器"的胶水，
属于技术实现细节；用例层（GenerateMaterial）只通过鸭子类型接收它，
不 import 它——洋葱方向不破坏（外层可以依赖内层的一切）。

两步流水线：
    1. LLM 单次结构化调用：把大纲 Markdown 整理成幻灯片数组
       （只排版不改写——铁律见 SLIDES_SYSTEM_PROMPT）；
    2. python-pptx 渲染：数组 → .pptx 落盘。

为什么不让 agent 直接"画"PPT？——渲染是确定性排版，交给代码；
只有"理解大纲结构"需要智能。这是"工作流 vs agent"边界的又一次应用。
"""

from __future__ import annotations

from pathlib import Path

from ...application.prompts import SLIDES_SCHEMA, SLIDES_SYSTEM_PROMPT
from ...domain.ports import LlmPort
from .pptx_renderer import render_pptx


class SlidesExporter:
    """把大纲导出成 .pptx。由装配根构建（LLM 与 generate 共用同一个计价器）。"""

    def __init__(self, llm: LlmPort):
        self.llm = llm

    def export(self, markdown_text: str, out_path: str | Path) -> dict:
        """导出。返回 {"path": Path, "slides": 页数}；LLM/渲染失败原样抛异常
        （由调用方决定降级——大纲 .md 已经在手，pptx 失败不该毁掉任务）。"""
        card = self.llm.complete_structured(
            system=SLIDES_SYSTEM_PROMPT,
            user=markdown_text,
            schema=SLIDES_SCHEMA,
        )
        slides = [
            {
                "title": str(s.get("title") or "未命名"),
                "bullets": [str(b) for b in (s.get("bullets") or []) if str(b).strip()],
            }
            for s in (card.get("slides") or [])
            if isinstance(s, dict)
        ]
        path = render_pptx(
            slides,
            out_path,
            title=str(card.get("title") or "参赛答辩"),
            subtitle=str(card.get("subtitle") or ""),
        )
        return {"path": path, "slides": len(slides)}
