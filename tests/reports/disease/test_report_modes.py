import pytest

from src.reports.disease.report_modes import (
    ReportModeError,
    company_layer_quotas,
    get_report_mode_config,
)


def test_report_modes_define_retained_limits_and_narrative_caps():
    assert get_report_mode_config("fast").retained_record_limit == 100
    assert get_report_mode_config("medium").retained_record_limit == 250
    assert get_report_mode_config("pro").retained_record_limit == 500
    assert get_report_mode_config(None).mode == "fast"
    assert get_report_mode_config(" MEDIUM ").mode == "medium"

    assert get_report_mode_config("medium").narrative_record_cap < 250
    assert get_report_mode_config("pro").narrative_record_cap < 500


def test_invalid_report_mode_is_rejected_cleanly():
    with pytest.raises(ReportModeError) as exc:
        get_report_mode_config("deep")

    assert "Invalid report_mode" in str(exc.value)
    assert exc.value.mode == "deep"


def test_company_layer_quotas_preserve_fast_shape_and_scale_large_modes():
    assert company_layer_quotas(80) == {
        "catalyst": 30,
        "expansion": 50,
        "track_record": 20,
    }
    assert company_layer_quotas(100) == {
        "catalyst": 30,
        "expansion": 50,
        "track_record": 20,
    }
    assert company_layer_quotas(250) == {
        "catalyst": 75,
        "expansion": 125,
        "track_record": 50,
    }
    assert company_layer_quotas(500) == {
        "catalyst": 150,
        "expansion": 250,
        "track_record": 100,
    }
