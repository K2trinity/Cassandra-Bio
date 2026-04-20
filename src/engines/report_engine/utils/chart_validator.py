"""Minimal legacy-compatible chart validation and repair helpers."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ValidationResult:
    """Validation output expected by legacy renderers."""

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class RepairResult:
    """Repair output expected by legacy renderers."""

    success: bool
    repaired_block: Optional[Dict[str, Any]] = None
    method: str = "local"
    changes: List[str] = field(default_factory=list)


class ChartValidator:
    """Validate chart widget payloads used by ReportEngine renderers."""

    def validate(self, block: Dict[str, Any]) -> ValidationResult:
        if not isinstance(block, dict):
            return ValidationResult(False, errors=["chart block must be an object"])

        widget_type = str(block.get("widgetType") or "")
        if not widget_type.startswith("chart.js"):
            return ValidationResult(True)

        errors: List[str] = []
        warnings: List[str] = []

        data = block.get("data")
        if not isinstance(data, dict):
            errors.append("chart.data must be an object")
            return ValidationResult(False, errors=errors, warnings=warnings)

        datasets = data.get("datasets")
        if not isinstance(datasets, list) or not datasets:
            errors.append("chart.data.datasets must be a non-empty list")
            return ValidationResult(False, errors=errors, warnings=warnings)

        max_length = 0
        for idx, dataset in enumerate(datasets):
            if not isinstance(dataset, dict):
                errors.append(f"chart.data.datasets[{idx}] must be an object")
                continue
            series = dataset.get("data")
            if not isinstance(series, list):
                errors.append(f"chart.data.datasets[{idx}].data must be a list")
                continue
            max_length = max(max_length, len(series))

        labels = data.get("labels")
        chart_type = self._detect_chart_type(block)
        if chart_type not in {"scatter", "bubble"}:
            if not isinstance(labels, list) or not labels:
                warnings.append("chart.data.labels missing for non-scatter chart")
            elif max_length and len(labels) != max_length:
                warnings.append("chart.data.labels length differs from dataset length")

        return ValidationResult(len(errors) == 0, errors=errors, warnings=warnings)

    @staticmethod
    def _detect_chart_type(block: Dict[str, Any]) -> str:
        props = block.get("props") if isinstance(block.get("props"), dict) else {}
        chart_type = props.get("type") if isinstance(props.get("type"), str) else ""
        if chart_type:
            return chart_type.lower()
        widget_type = str(block.get("widgetType") or "")
        if widget_type.startswith("chart.js."):
            return widget_type.split("chart.js.", 1)[1].lower()
        return "bar"


class ChartRepairer:
    """Repair common chart payload issues with deterministic local fixes."""

    def __init__(
        self,
        validator: ChartValidator,
        llm_repair_fns: Optional[List[Callable[[Dict[str, Any], ValidationResult], Optional[Dict[str, Any]]]]] = None,
    ):
        self.validator = validator
        self.llm_repair_fns = llm_repair_fns or []

    def build_cache_key(self, block: Dict[str, Any]) -> str:
        snapshot = copy.deepcopy(block if isinstance(block, dict) else {})
        if isinstance(snapshot, dict):
            for key in list(snapshot.keys()):
                if str(key).startswith("_chart_"):
                    snapshot.pop(key, None)
        payload = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, default=str)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def repair(
        self,
        block: Dict[str, Any],
        validation_result: Optional[ValidationResult] = None,
    ) -> RepairResult:
        if not isinstance(block, dict):
            return RepairResult(False, changes=["input block is not an object"])

        repaired = copy.deepcopy(block)
        changes: List[str] = []

        if repaired.get("type") != "widget":
            repaired["type"] = "widget"
            changes.append("normalized type to widget")

        widget_type = str(repaired.get("widgetType") or "")
        if not widget_type.startswith("chart.js"):
            repaired["widgetType"] = "chart.js.bar"
            changes.append("added default widgetType chart.js.bar")

        props = repaired.get("props")
        if not isinstance(props, dict):
            props = {}
            repaired["props"] = props
            changes.append("created props object")

        chart_type = ChartValidator._detect_chart_type(repaired)
        if not isinstance(props.get("type"), str) or not props.get("type"):
            props["type"] = chart_type
            changes.append("filled props.type from widgetType")

        data = repaired.get("data")
        if not isinstance(data, dict):
            data = {}
            repaired["data"] = data
            changes.append("created data object")

        datasets = data.get("datasets")
        if not isinstance(datasets, list):
            datasets = []
            data["datasets"] = datasets
            changes.append("normalized datasets to list")

        normalized_sets: List[Dict[str, Any]] = []
        max_len = 0
        for idx, dataset in enumerate(datasets):
            if not isinstance(dataset, dict):
                dataset = {"label": f"Series {idx + 1}", "data": []}
                changes.append(f"coerced dataset {idx} to object")

            series = dataset.get("data")
            if not isinstance(series, list):
                series = [series] if series is not None else []
                changes.append(f"coerced dataset {idx} data to list")

            clean_series: List[Any] = []
            for point in series:
                if isinstance(point, dict):
                    if "y" in point:
                        clean_series.append(point)
                    elif "value" in point:
                        clean_series.append(point.get("value"))
                    else:
                        clean_series.append(0)
                elif isinstance(point, (int, float)):
                    clean_series.append(point)
                elif point is None:
                    clean_series.append(0)
                else:
                    try:
                        clean_series.append(float(point))
                    except Exception:
                        clean_series.append(0)

            dataset["data"] = clean_series
            if not isinstance(dataset.get("label"), str) or not dataset.get("label"):
                dataset["label"] = f"Series {idx + 1}"
            max_len = max(max_len, len(clean_series))
            normalized_sets.append(dataset)

        if not normalized_sets:
            normalized_sets = [{"label": "Series 1", "data": [0]}]
            max_len = 1
            changes.append("created fallback dataset")

        data["datasets"] = normalized_sets

        labels = data.get("labels")
        if not isinstance(labels, list) or not labels:
            if chart_type not in {"scatter", "bubble"}:
                data["labels"] = [f"Item {i + 1}" for i in range(max_len or 1)]
                changes.append("generated fallback labels")

        post_validation = self.validator.validate(repaired)
        if post_validation.is_valid:
            return RepairResult(True, repaired_block=repaired, method="local", changes=changes)

        # Optional API/LLM fallback hooks.
        for repair_fn in self.llm_repair_fns:
            try:
                candidate = repair_fn(copy.deepcopy(repaired), post_validation)
            except Exception:
                continue
            if not isinstance(candidate, dict):
                continue
            candidate_result = self.validator.validate(candidate)
            if candidate_result.is_valid:
                return RepairResult(
                    True,
                    repaired_block=candidate,
                    method="api",
                    changes=changes + ["repaired by external hook"],
                )

        failure_changes = changes + post_validation.errors
        return RepairResult(False, repaired_block=None, method="none", changes=failure_changes)


def create_chart_validator() -> ChartValidator:
    return ChartValidator()


def create_chart_repairer(
    validator: Optional[ChartValidator] = None,
    llm_repair_fns: Optional[List[Callable[[Dict[str, Any], ValidationResult], Optional[Dict[str, Any]]]]] = None,
) -> ChartRepairer:
    return ChartRepairer(validator=validator or ChartValidator(), llm_repair_fns=llm_repair_fns)


__all__ = [
    "ValidationResult",
    "RepairResult",
    "ChartValidator",
    "ChartRepairer",
    "create_chart_validator",
    "create_chart_repairer",
]
