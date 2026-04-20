"""Compatibility ChapterGenerationNode for the canonical engine package.

This implementation keeps the legacy sanitizer helpers and constructor shape
used by tests while avoiding the older Chapter/ChapterBlock data model.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..ir import ENGINE_AGENT_TITLES, IRValidator


class ChapterGenerationNode:
    """Legacy-compatible chapter node with sanitizer helpers."""

    _ALLOWED_ENGINE_QUOTE_MARKS = {"bold", "italic"}

    def __init__(self, llm_client: Any = None, validator: IRValidator | None = None, storage: Any = None):
        self.llm = llm_client
        self.validator = validator or IRValidator()
        self.storage = storage

    def _sanitize_chapter_blocks(self, chapter: Dict[str, Any]) -> None:
        """Mutate chapter blocks in-place to satisfy renderer contract expectations."""
        blocks = chapter.get("blocks")
        if not isinstance(blocks, list):
            chapter["blocks"] = []
            return

        for block in blocks:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")
            if block_type == "table":
                self._sanitize_table_block(block)
            elif block_type == "engineQuote":
                self._sanitize_engine_quote_block(block)

    def _sanitize_table_block(self, block: Dict[str, Any]) -> None:
        rows = block.get("rows")
        if not isinstance(rows, list):
            block["rows"] = []
            return

        normalized_rows: List[Dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                cells = row.get("cells")
                if not isinstance(cells, list):
                    seed_text = self._extract_text(row.get("text") if "text" in row else row)
                    cells = [{"blocks": [self._paragraph_block(seed_text)]}]
                row["cells"] = [self._sanitize_table_cell(cell) for cell in cells]
                normalized_rows.append(row)
                continue

            normalized_rows.append(
                {
                    "cells": [
                        {
                            "blocks": [self._paragraph_block(self._extract_text(row))],
                        }
                    ]
                }
            )

        block["rows"] = normalized_rows

    def _sanitize_table_cell(self, cell: Any) -> Dict[str, Any]:
        if not isinstance(cell, dict):
            return {"blocks": [self._paragraph_block(self._extract_text(cell))]}

        blocks = cell.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            seed_text = self._extract_text(cell.get("text") if "text" in cell else cell)
            cell["blocks"] = [self._paragraph_block(seed_text)]
            return cell

        normalized_blocks: List[Dict[str, Any]] = []
        for block in blocks:
            normalized_blocks.append(self._normalize_paragraph_block(block))

        cell["blocks"] = normalized_blocks or [self._paragraph_block(self._extract_text(cell))]
        return cell

    def _sanitize_engine_quote_block(self, block: Dict[str, Any]) -> None:
        engine_raw = block.get("engine")
        engine = engine_raw.lower() if isinstance(engine_raw, str) else ""
        if engine in ENGINE_AGENT_TITLES:
            block["title"] = ENGINE_AGENT_TITLES[engine]

        inner = block.get("blocks")
        if not isinstance(inner, list):
            inner = []

        normalized_inner: List[Dict[str, Any]] = []
        for inner_block in inner:
            normalized_inner.append(self._normalize_engine_quote_inner(inner_block))

        if not normalized_inner:
            normalized_inner.append(self._paragraph_block("Insufficient data"))

        block["blocks"] = normalized_inner

    def _normalize_engine_quote_inner(self, block: Any) -> Dict[str, Any]:
        paragraph = self._normalize_paragraph_block(block)

        inlines = paragraph.get("inlines", [])
        sanitized_inlines: List[Dict[str, Any]] = []
        for inline in inlines:
            if not isinstance(inline, dict):
                sanitized_inlines.append({"text": self._extract_text(inline), "marks": []})
                continue

            marks = inline.get("marks")
            filtered_marks: List[Dict[str, Any]] = []
            if isinstance(marks, list):
                for mark in marks:
                    if not isinstance(mark, dict):
                        continue
                    mark_type = mark.get("type")
                    if mark_type in self._ALLOWED_ENGINE_QUOTE_MARKS:
                        filtered_marks.append({"type": mark_type})

            sanitized_inlines.append(
                {
                    "text": str(inline.get("text") or ""),
                    "marks": filtered_marks,
                }
            )

        paragraph["inlines"] = sanitized_inlines or [{"text": "", "marks": []}]
        return paragraph

    def _normalize_paragraph_block(self, block: Any) -> Dict[str, Any]:
        if isinstance(block, dict) and block.get("type") == "paragraph":
            inlines = block.get("inlines")
            if isinstance(inlines, list) and inlines:
                normalized_inlines: List[Dict[str, Any]] = []
                for inline in inlines:
                    if isinstance(inline, dict):
                        text = str(inline.get("text") or "")
                        marks = inline.get("marks")
                        normalized_inlines.append(
                            {
                                "text": text,
                                "marks": marks if isinstance(marks, list) else [],
                            }
                        )
                    else:
                        normalized_inlines.append({"text": self._extract_text(inline), "marks": []})
                block["inlines"] = normalized_inlines
                return block

            text = self._extract_text(block.get("text") if "text" in block else block)
            return self._paragraph_block(text)

        return self._paragraph_block(self._extract_text(block))

    def _paragraph_block(self, text: str) -> Dict[str, Any]:
        return {
            "type": "paragraph",
            "inlines": [
                {
                    "text": text,
                    "marks": [],
                }
            ],
        }

    def _extract_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, dict):
            if isinstance(value.get("text"), str):
                return value["text"]
            inlines = value.get("inlines")
            if isinstance(inlines, list):
                parts: List[str] = []
                for item in inlines:
                    if isinstance(item, dict):
                        parts.append(str(item.get("text") or ""))
                    else:
                        parts.append(self._extract_text(item))
                return " ".join(p for p in parts if p).strip()
            items = value.get("items")
            if isinstance(items, list):
                return self._extract_text(items)
            if isinstance(value.get("title"), str):
                return value["title"]
            return ""
        if isinstance(value, list):
            parts = [self._extract_text(item) for item in value]
            return " ".join(p for p in parts if p).strip()
        return str(value)


def create_chapter_generation_node(*args: Any, **kwargs: Any) -> ChapterGenerationNode:
    """Factory kept for backward compatibility."""
    return ChapterGenerationNode(*args, **kwargs)


__all__ = ["ChapterGenerationNode", "create_chapter_generation_node"]
