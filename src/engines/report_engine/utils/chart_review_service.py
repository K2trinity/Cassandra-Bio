"""Thread-safe document-level chart review service."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from .chart_repair_api import create_llm_repair_functions
from .chart_validator import ChartRepairer, ChartValidator, ValidationResult, create_chart_repairer, create_chart_validator


@dataclass
class ReviewStats:
    total: int = 0
    valid: int = 0
    repaired_locally: int = 0
    repaired_api: int = 0
    failed: int = 0

    @property
    def repaired_total(self) -> int:
        return self.repaired_locally + self.repaired_api

    def to_dict(self) -> Dict[str, int]:
        return {
            "total": self.total,
            "valid": self.valid,
            "repaired_locally": self.repaired_locally,
            "repaired_api": self.repaired_api,
            "failed": self.failed,
        }


class ChartReviewService:
    """Validate and repair chart widgets in a full document tree."""

    def __init__(self, validator: ChartValidator | None = None, repairer: ChartRepairer | None = None):
        self.validator = validator or create_chart_validator()
        self.repairer = repairer or create_chart_repairer(
            validator=self.validator,
            llm_repair_fns=create_llm_repair_functions(),
        )
        self._lock = threading.Lock()

    def review_document(
        self,
        document_ir: Dict[str, Any],
        *,
        ir_file_path: str | None = None,
        reset_stats: bool = True,
        save_on_repair: bool = False,
    ) -> ReviewStats:
        del reset_stats  # Kept for API compatibility.

        if not isinstance(document_ir, dict):
            return ReviewStats()

        stats = ReviewStats()
        repaired_any = False

        with self._lock:
            def walk(node: Any) -> None:
                nonlocal repaired_any
                if isinstance(node, dict):
                    if self._is_chart_widget(node):
                        stats.total += 1
                        validation = self.validator.validate(node)
                        if validation.is_valid:
                            stats.valid += 1
                            self._mark_valid(node)
                        else:
                            repair = self.repairer.repair(node, validation)
                            if repair.success and isinstance(repair.repaired_block, dict):
                                node.clear()
                                node.update(repair.repaired_block)
                                method = (repair.method or "local").lower()
                                if method == "api":
                                    stats.repaired_api += 1
                                else:
                                    stats.repaired_locally += 1
                                self._mark_repaired(node, method)
                                repaired_any = True
                            else:
                                stats.failed += 1
                                self._mark_failed(node, validation)

                    for value in node.values():
                        walk(value)
                    return

                if isinstance(node, list):
                    for item in node:
                        walk(item)

            walk(document_ir)

            if save_on_repair and repaired_any and ir_file_path:
                path = Path(ir_file_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(document_ir, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

        return stats

    @staticmethod
    def _is_chart_widget(block: Dict[str, Any]) -> bool:
        widget_type = block.get("widgetType")
        return isinstance(widget_type, str) and widget_type.startswith("chart.js")

    @staticmethod
    def _mark_valid(block: Dict[str, Any]) -> None:
        block["_chart_reviewed"] = True
        block["_chart_review_status"] = "valid"
        block["_chart_review_method"] = "none"
        block["_chart_renderable"] = True
        block.pop("_chart_error_reason", None)

    @staticmethod
    def _mark_repaired(block: Dict[str, Any], method: str) -> None:
        block["_chart_reviewed"] = True
        block["_chart_review_status"] = "repaired"
        block["_chart_review_method"] = method
        block["_chart_renderable"] = True
        block.pop("_chart_error_reason", None)

    @staticmethod
    def _mark_failed(block: Dict[str, Any], validation: ValidationResult) -> None:
        reason = validation.errors[0] if validation.errors else "Invalid chart payload"
        block["_chart_reviewed"] = True
        block["_chart_review_status"] = "failed"
        block["_chart_review_method"] = "none"
        block["_chart_renderable"] = False
        block["_chart_error_reason"] = reason


_SERVICE_LOCK = threading.Lock()
_SERVICE_INSTANCE: ChartReviewService | None = None


def get_chart_review_service() -> ChartReviewService:
    """Return a process-wide singleton review service."""
    global _SERVICE_INSTANCE
    with _SERVICE_LOCK:
        if _SERVICE_INSTANCE is None:
            _SERVICE_INSTANCE = ChartReviewService()
        return _SERVICE_INSTANCE


__all__ = ["ReviewStats", "ChartReviewService", "get_chart_review_service"]
