"""
Markdown Renderer

将 IRDocument 转回 Markdown 格式（纯文本，最轻量级输出）。
适用于：
- 纯文本导出
- 进一步 LLM 处理
- 调试查看
"""

from typing import List, Any
from src.report_engine.ir.schema import IRDocument, Chapter, ChapterBlock, BlockType
import json


class MarkdownRenderer:
    """从 IRDocument 生成 Markdown 字符串"""

    def render(self, doc: IRDocument) -> str:
        lines: List[str] = []

        # Title
        lines.append(f"# {doc.title}")
        if doc.subtitle:
            lines.append(f"*{doc.subtitle}*")
        if doc.query:
            lines.append(f"\n> **Query**: {doc.query}")
        lines.append("")

        for chapter in sorted(doc.chapters, key=lambda c: c.order):
            lines.extend(self._render_chapter(chapter))

        return "\n".join(lines)

    def _render_chapter(self, chapter: Chapter) -> List[str]:
        lines = ["---", f"## {chapter.title}", ""]
        for block in chapter.blocks:
            lines.extend(self._render_block(block))
        return lines

    def _render_block(self, block: ChapterBlock) -> List[str]:
        t = block.type
        if t == BlockType.HEADING:
            level = block.level or 3
            return [f"{'#' * level} {block.content}", ""]
        elif t == BlockType.PARAGRAPH:
            return [str(block.content), ""]
        elif t == BlockType.LIST:
            ordered = block.metadata.get("ordered", False)
            items = []
            for i, item in enumerate(block.content, 1):
                txt = str(item.get("text", item)) if isinstance(item, dict) else str(item)
                prefix = f"{i}." if ordered else "-"
                items.append(f"{prefix} {txt}")
            return items + [""]
        elif t == BlockType.QUOTE:
            source = block.metadata.get("source", "")
            lines = [f"> {block.content}"]
            if source:
                lines.append(f"> — *{source}*")
            return lines + [""]
        elif t == BlockType.CALLOUT:
            variant = block.metadata.get("variant", "info").upper()
            title = block.metadata.get("title", variant)
            return [
                f"> **[{title}]**",
                f"> {block.content}",
                "",
            ]
        elif t == BlockType.CODE:
            lang = block.metadata.get("language", "")
            return [f"```{lang}", str(block.content), "```", ""]
        elif t == BlockType.DIVIDER:
            return ["---", ""]
        elif t == BlockType.IMAGE:
            caption = block.metadata.get("caption", "figure")
            return [f"![{caption}]({block.content})", ""]
        elif t == BlockType.FORMULA:
            display = block.metadata.get("display", True)
            if display:
                return [f"$$\n{block.content}\n$$", ""]
            return [f"${block.content}$"]
        elif t == BlockType.TABLE:
            return self._render_table_md(block)
        elif t == BlockType.CHART:
            chart_data = block.content if isinstance(block.content, dict) else {}
            title = chart_data.get("title", "Chart")
            labels = chart_data.get("labels", [])
            datasets = chart_data.get("datasets", [])
            lines = [f"**[Chart: {title}]**"]
            for ds in datasets:
                ds_label = ds.get("label", "")
                data = ds.get("data", [])
                if labels and data:
                    row = " | ".join(f"{l}: {v}" for l, v in zip(labels, data))
                    lines.append(f"- {ds_label}: {row}")
            return lines + [""]
        elif t == BlockType.WORDCLOUD:
            words = block.content
            if isinstance(words, dict):
                top = sorted(words.items(), key=lambda x: x[1], reverse=True)[:10]
            elif isinstance(words, list):
                top = sorted(words, key=lambda x: x.get("weight", 1) if isinstance(x, dict) else 1, reverse=True)[:10]
                top = [(x.get("word", str(x)) if isinstance(x, dict) else str(x[0]), x.get("weight", 1) if isinstance(x, dict) else x[1]) for x in top]
            else:
                top = []
            word_str = ", ".join(f"{w}({round(s, 1)})" for w, s in top)
            return [f"**[WordCloud]** Top words: {word_str}", ""]
        else:
            return [str(block.content), ""]

    def _render_table_md(self, block: ChapterBlock) -> List[str]:
        data = block.content
        if not isinstance(data, dict):
            return [str(data), ""]
        headers = data.get("headers", [])
        rows = data.get("rows", [])
        caption = data.get("caption", "")
        lines = []
        if caption:
            lines.append(f"*{caption}*")
        if headers:
            lines.append("| " + " | ".join(str(h) for h in headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
        lines.append("")
        return lines
