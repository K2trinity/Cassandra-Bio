from __future__ import annotations

from dataclasses import dataclass


class ReportModeError(ValueError):
    def __init__(self, mode: object) -> None:
        self.mode = str(mode or "").strip()
        super().__init__(
            "Invalid report_mode. Expected one of: fast, medium, pro."
        )


@dataclass(frozen=True)
class ReportModeConfig:
    mode: str
    retained_record_limit: int
    narrative_record_cap: int
    narrative_risk_record_cap: int


REPORT_MODES: dict[str, ReportModeConfig] = {
    "fast": ReportModeConfig(
        mode="fast",
        retained_record_limit=100,
        narrative_record_cap=100,
        narrative_risk_record_cap=100,
    ),
    "medium": ReportModeConfig(
        mode="medium",
        retained_record_limit=250,
        narrative_record_cap=120,
        narrative_risk_record_cap=120,
    ),
    "pro": ReportModeConfig(
        mode="pro",
        retained_record_limit=500,
        narrative_record_cap=150,
        narrative_risk_record_cap=150,
    ),
}
DEFAULT_REPORT_MODE = "fast"
COMPANY_LAYER_RATIOS: dict[str, float] = {
    "catalyst": 0.30,
    "expansion": 0.50,
    "track_record": 0.20,
}
FAST_COMPANY_LAYER_PAGE_SIZES: dict[str, int] = {
    "catalyst": 30,
    "expansion": 50,
    "track_record": 20,
}


def normalize_report_mode(mode: object | None) -> str:
    text = str(mode or DEFAULT_REPORT_MODE).strip().lower()
    if not text:
        text = DEFAULT_REPORT_MODE
    if text not in REPORT_MODES:
        raise ReportModeError(mode)
    return text


def get_report_mode_config(mode: object | None = None) -> ReportModeConfig:
    return REPORT_MODES[normalize_report_mode(mode)]


def company_layer_quotas(max_records: int) -> dict[str, int]:
    limit = max(0, int(max_records))
    if limit <= 100:
        return dict(FAST_COMPANY_LAYER_PAGE_SIZES)
    catalyst = round(limit * COMPANY_LAYER_RATIOS["catalyst"])
    expansion = round(limit * COMPANY_LAYER_RATIOS["expansion"])
    track_record = max(0, limit - catalyst - expansion)
    return {
        "catalyst": catalyst,
        "expansion": expansion,
        "track_record": track_record,
    }


__all__ = [
    "DEFAULT_REPORT_MODE",
    "ReportModeConfig",
    "ReportModeError",
    "company_layer_quotas",
    "get_report_mode_config",
    "normalize_report_mode",
]
