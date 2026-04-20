"""Compatibility-first IR validator.

This validator accepts both the legacy dataclass-based chapter layout used by
existing tests and the newer JSON-style chapter layout used by the engine
package. It keeps validation intentionally lightweight so the renderer can
consume either shape without import-time failures.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .schema import (
    ALLOWED_BLOCK_TYPES,
    ALLOWED_INLINE_MARKS,
    BlockType,
    ENGINE_AGENT_TITLES,
    IR_VERSION,
)


class IRValidator:
    """Validate and lightly normalize chapter-level IR payloads."""

    def __init__(self, schema_version: str = IR_VERSION):
        self.schema_version = schema_version

    def validate_chapter(self, chapter: Dict[str, Any]) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        if not isinstance(chapter, dict):
            return False, ["chapter必须是对象"]

        if "title" not in chapter:
            errors.append("missing chapter.title")
        if "blocks" not in chapter:
            errors.append("missing chapter.blocks")
        if not isinstance(chapter.get("blocks"), list) or not chapter.get("blocks"):
            errors.append("chapter.blocks必须是非空数组")
            return False, errors

        for index, block in enumerate(chapter.get("blocks", [])):
            self._validate_block(block, f"blocks[{index}]", errors)

        return len(errors) == 0, errors

    def validate_and_fix(self, chapter: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], List[str]]:
        fixed = dict(chapter) if isinstance(chapter, dict) else {}
        fixed_blocks: List[Dict[str, Any]] = []
        for block in fixed.get("blocks", []) if isinstance(fixed.get("blocks"), list) else []:
            fixed_blocks.append(self._fix_block(block, 0))
        fixed["blocks"] = fixed_blocks
        valid, errors = self.validate_chapter(fixed)
        return valid, fixed, errors

    def check_content_quality(self, chapter: Any) -> Tuple[bool, List[str]]:
        blocks = getattr(chapter, "blocks", None)
        if blocks is None and isinstance(chapter, dict):
            blocks = chapter.get("blocks")
        if not isinstance(blocks, list):
            return False, ["chapter.blocks必须是数组"]

        non_heading_blocks = 0
        warnings: List[str] = []
        for block in blocks:
            block_type = self._block_type_name(block)
            if block_type != BlockType.HEADING.value:
                non_heading_blocks += 1
            if block_type == BlockType.PARAGRAPH.value:
                text = self._block_text(block)
                if len(text.strip()) < 20:
                    warnings.append("paragraph content too short")

        if non_heading_blocks == 0:
            warnings.append("chapter contains no substantive blocks")
        return len(warnings) == 0, warnings

    def _validate_block(self, block: Any, path: str, errors: List[str]) -> None:
        if not isinstance(block, dict):
            errors.append(f"{path} 必须是对象")
            return

        block_type = self._normalized_block_type(block)
        if block_type not in set(ALLOWED_BLOCK_TYPES) | {BlockType.CHART.value, BlockType.WORDCLOUD.value, "engineQuote"}:
            errors.append(f"{path}.type 不被支持: {block.get('type')}")
            return

        if block_type == BlockType.HEADING.value:
            if "text" not in block and "content" not in block:
                errors.append(f"{path}.text 缺失")
            if "level" not in block:
                errors.append(f"{path}.level 必须是整数")
            return

        if block_type == BlockType.PARAGRAPH.value:
            if "inlines" in block:
                inlines = block.get("inlines")
                if not isinstance(inlines, list) or not inlines:
                    errors.append(f"{path}.inlines 必须是非空数组")
                    return
                for idx, run in enumerate(inlines):
                    self._validate_inline_run(run, f"{path}.inlines[{idx}]", errors)
                return
            if "content" not in block:
                errors.append(f"{path}.content 缺失")
            return

        if block_type == BlockType.LIST.value:
            items = block.get("items")
            if not isinstance(items, list) or not items:
                errors.append(f"{path}.items 必须是非空列表")
            return

        if block_type == BlockType.TABLE.value:
            rows = block.get("rows")
            if not isinstance(rows, list) or not rows:
                errors.append(f"{path}.rows 必须是非空数组")
            return

        if block_type == BlockType.QUOTE.value:
            inner = block.get("blocks")
            if not isinstance(inner, list) or not inner:
                errors.append(f"{path}.blocks 必须是非空数组")
            return

        if block_type == BlockType.CALLOUT.value:
            inner = block.get("blocks")
            if not isinstance(inner, list) or not inner:
                errors.append(f"{path}.blocks 必须是非空数组")
            return

        if block_type == BlockType.CHART.value:
            content = block.get("content")
            if not isinstance(content, dict):
                errors.append(f"{path}.content 必须是dict对象")
                return
            if "type" not in content:
                errors.append(f"{path}.content.type 缺失")
            datasets = content.get("datasets")
            if not isinstance(datasets, list):
                errors.append(f"{path}.content.datasets 必须是数组")
            elif not datasets:
                errors.append(f"{path}.content.datasets 不能为空")
            else:
                for idx, dataset in enumerate(datasets):
                    if not isinstance(dataset, dict):
                        errors.append(f"{path}.content.datasets[{idx}] 必须是对象")
                        continue
                    if "data" not in dataset:
                        errors.append(f"{path}.content.datasets[{idx}].data 缺失")
            return

        if block_type == BlockType.WORDCLOUD.value:
            return

        if block_type == "engineQuote":
            self._validate_engineQuote_block(block, path, errors)
            return

        if block_type == BlockType.CODE.value:
            if "content" not in block:
                errors.append(f"{path}.content 缺失")
            return

        if block_type == BlockType.FORMULA.value:
            if "latex" not in block and "content" not in block:
                errors.append(f"{path}.latex 缺失")
            return

        if block_type == BlockType.IMAGE.value:
            if "content" not in block and "img" not in block:
                errors.append(f"{path}.content 缺失")
            return

    def _validate_inline_run(self, run: Any, path: str, errors: List[str]) -> None:
        if not isinstance(run, dict):
            errors.append(f"{path} 必须是对象")
            return
        if "text" not in run:
            errors.append(f"{path}.text 缺失")
        marks = run.get("marks", [])
        if not isinstance(marks, list):
            errors.append(f"{path}.marks 必须是数组")
            return
        for idx, mark in enumerate(marks):
            if not isinstance(mark, dict):
                errors.append(f"{path}.marks[{idx}] 必须是对象")
                continue
            if mark.get("type") not in ALLOWED_INLINE_MARKS:
                errors.append(f"{path}.marks[{idx}].type 不被支持: {mark.get('type')}")

    def _validate_engineQuote_block(self, block: Dict[str, Any], path: str, errors: List[str]) -> None:
        engine_raw = block.get("engine")
        engine = engine_raw.lower() if isinstance(engine_raw, str) else None
        expected_title = ENGINE_AGENT_TITLES.get(engine) if engine else None
        title = block.get("title")

        if engine not in {"insight", "media", "query"}:
            errors.append(f"{path}.engine 取值非法: {engine_raw}")
        if title is None:
            errors.append(f"{path}.title 缺失")
        elif expected_title and title != expected_title:
            errors.append(f"{path}.title 必须与engine一致，使用对应Agent名称: {expected_title}")

        inner = block.get("blocks")
        if not isinstance(inner, list) or not inner:
            errors.append(f"{path}.blocks 必须是非空数组")
            return
        for idx, sub_block in enumerate(inner):
            sub_path = f"{path}.blocks[{idx}]"
            if not isinstance(sub_block, dict):
                errors.append(f"{sub_path} 必须是对象")
                continue
            if sub_block.get("type") != "paragraph":
                errors.append(f"{sub_path}.type 仅允许 paragraph")
                continue
            inlines = sub_block.get("inlines")
            if not isinstance(inlines, list) or not inlines:
                errors.append(f"{sub_path}.inlines 必须是非空数组")
                continue
            for ridx, run in enumerate(inlines):
                self._validate_inline_run(run, f"{sub_path}.inlines[{ridx}]", errors)
                if not isinstance(run, dict):
                    continue
                marks = run.get("marks") or []
                if not isinstance(marks, list):
                    errors.append(f"{sub_path}.inlines[{ridx}].marks 必须是数组")
                    continue
                for midx, mark in enumerate(marks):
                    mark_type = mark.get("type") if isinstance(mark, dict) else None
                    if mark_type not in {"bold", "italic"}:
                        errors.append(f"{sub_path}.inlines[{ridx}].marks[{midx}].type 仅允许 bold/italic")

    def _fix_block(self, block: Any, _depth: int = 0) -> Dict[str, Any]:
        if not isinstance(block, dict):
            return {
                "type": BlockType.CHART.value,
                "content": {
                    "type": "bar",
                    "title": "Chart",
                    "labels": [],
                    "datasets": [{"label": "Series 1", "data": [0]}],
                },
            }

        fixed = dict(block)
        raw_type = str(fixed.get("type") or "paragraph")
        alias_map = {
            "graph": BlockType.CHART.value,
            "visualization": BlockType.CHART.value,
            "Chart": BlockType.CHART.value,
            "chart": BlockType.CHART.value,
            "wordcloud": BlockType.WORDCLOUD.value,
            "word_cloud": BlockType.WORDCLOUD.value,
        }
        fixed["type"] = alias_map.get(raw_type, raw_type.lower())

        if fixed["type"] == BlockType.CHART.value:
            content = fixed.get("content")
            if not isinstance(content, dict):
                content = {}
            chart_type = str(content.get("type") or "bar")
            datasets = content.get("datasets")
            if not isinstance(datasets, list) or not datasets:
                datasets = [{"label": "Series 1", "data": [0]}]
            content["type"] = chart_type
            content.setdefault("title", "Chart")
            content.setdefault("labels", [])
            content["datasets"] = datasets
            fixed["content"] = content

        return fixed

    @staticmethod
    def _block_type_name(block: Any) -> str:
        if isinstance(block, dict):
            value = block.get("type")
            if isinstance(value, str):
                return value.lower()
        return ""

    @classmethod
    def _normalized_block_type(cls, block: Any) -> str:
        raw = cls._block_type_name(block)
        alias_map = {
            "blockquote": BlockType.QUOTE.value,
            "quote": BlockType.QUOTE.value,
            "callout": BlockType.CALLOUT.value,
            "enginequote": "engineQuote",
            "wordcloud": BlockType.WORDCLOUD.value,
            "word_cloud": BlockType.WORDCLOUD.value,
            "chart": BlockType.CHART.value,
            "graph": BlockType.CHART.value,
            "visualization": BlockType.CHART.value,
            "figure": BlockType.IMAGE.value,
            "image": BlockType.IMAGE.value,
            "hr": BlockType.DIVIDER.value,
            "divider": BlockType.DIVIDER.value,
            "formula": BlockType.FORMULA.value,
            "math": BlockType.FORMULA.value,
        }
        return alias_map.get(raw, raw)

    @staticmethod
    def _block_text(block: Any) -> str:
        if isinstance(block, dict):
            if isinstance(block.get("content"), str):
                return block["content"]
            if isinstance(block.get("text"), str):
                return block["text"]
            inlines = block.get("inlines")
            if isinstance(inlines, list):
                parts = []
                for run in inlines:
                    if isinstance(run, dict) and isinstance(run.get("text"), str):
                        parts.append(run["text"])
                return " ".join(parts)
        return str(block or "")


__all__ = ["IRValidator"]
