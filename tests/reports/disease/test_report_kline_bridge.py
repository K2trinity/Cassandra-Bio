from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.reports.disease.models import (
    ClinicalTrialRecord,
    DiseaseProfile,
    DiseaseReportPackage,
    SourceAudit,
)


@pytest.fixture(autouse=True)
def isolated_events_db(tmp_path, monkeypatch):
    from src.backtest import events_db

    monkeypatch.setattr(events_db, "DB_PATH", tmp_path / "events.db")


def _company_profile(company_name: str = "Eli Lilly and Company") -> DiseaseProfile:
    return DiseaseProfile(
        query=f"company pipeline for {company_name}",
        target_type="company",
        company_name=company_name,
        sponsor_query=None,
        target_name=company_name,
        disease_name=company_name,
        canonical_condition=company_name,
        condition_terms=[],
        normalized_terms=[],
        expert_topic_url="https://clinicaltrials.gov/search?query.spons=Eli%20Lilly%20and%20Company",
        expert_full_match_url="https://clinicaltrials.gov/search?query.spons=Eli%20Lilly%20and%20Company",
    )


def _disease_profile() -> DiseaseProfile:
    return DiseaseProfile(
        query="Alzheimer disease landscape",
        target_type="disease",
        company_name=None,
        sponsor_query=None,
        target_name="Alzheimer Disease",
        disease_name="Alzheimer Disease",
        canonical_condition="Alzheimer Disease",
        condition_terms=["Alzheimer Disease"],
        normalized_terms=["alzheimer disease"],
        expert_topic_url="https://clinicaltrials.gov/search?cond=Alzheimer%20Disease",
        expert_full_match_url="https://clinicaltrials.gov/search?cond=Alzheimer%20Disease",
    )


def _trial(
    nct_number: str,
    *,
    sponsor: str = "Eli Lilly and Company",
    status: str = "COMPLETED",
    results_first_posted: date | None = date(2026, 4, 20),
    primary_completion_date: date | None = date(2026, 3, 15),
    completion_date: date | None = date(2026, 3, 30),
    last_update_posted: date | None = date(2026, 4, 25),
) -> ClinicalTrialRecord:
    return ClinicalTrialRecord(
        study_title=f"Study {nct_number} of donanemab in Alzheimer Disease",
        nct_number=nct_number,
        status=status,
        phases=["PHASE3"],
        has_results=results_first_posted is not None,
        study_results="Results available" if results_first_posted else "No posted results",
        results_first_posted=results_first_posted,
        last_update_posted=last_update_posted,
        primary_completion_date=primary_completion_date,
        completion_date=completion_date,
        conditions=["Alzheimer Disease"],
        interventions=["Donanemab"],
        sponsor=sponsor,
        study_type="INTERVENTIONAL",
        source_url=f"https://clinicaltrials.gov/study/{nct_number}",
    )


def _package(
    *,
    profile: DiseaseProfile | None = None,
    trials: list[ClinicalTrialRecord] | None = None,
    retained_count: int | None = None,
) -> DiseaseReportPackage:
    resolved_profile = profile or _company_profile()
    resolved_trials = trials if trials is not None else [
        _trial("NCT00000001"),
        _trial("NCT00000002", results_first_posted=None),
        _trial("NCT00000003", status="TERMINATED"),
    ]
    return DiseaseReportPackage(
        disease_profile=resolved_profile,
        clinical_trials=resolved_trials,
        risk_records=[],
        source_audit=SourceAudit(
            topic_url=resolved_profile.expert_topic_url,
            full_match_url=resolved_profile.expert_full_match_url,
            raw_count=len(resolved_trials),
            retained_count=len(resolved_trials) if retained_count is None else retained_count,
            rejected_count=0,
            generated_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
        ),
    )


def test_company_report_bridge_inserts_stable_trusted_events_for_kline_universe():
    from src.backtest.events_db import get_trusted_events_for_chart
    from src.reports.disease.report_kline_bridge import ReportKlineBridge

    package = _package()

    first = ReportKlineBridge().run(package)
    second = ReportKlineBridge().run(package)

    assert first["status"] == "ready"
    assert first["ticker"] == "LLY"
    assert first["company_name"] == "Eli Lilly and Company"
    assert first["kline_url"] == "/kline/LLY"
    assert first["event_count"] > 0
    assert first["inserted_event_count"] == first["event_count"]
    assert second["status"] == "ready"
    assert second["event_count"] == first["event_count"]

    events = get_trusted_events_for_chart("LLY")
    assert len(events) == first["event_count"]
    assert {event["ticker"] for event in events} == {"LLY"}
    assert {event["ticker_scope"] for event in events} == {"LLY"}
    assert {event["trust_status"] for event in events} == {"trusted"}
    assert {event["ownership_status"] for event in events} == {"owned"}
    assert all(event["source"] == "clinicaltrials" for event in events)
    assert all(event["source_ids"] for event in events)
    assert all(event["source_url"] for event in events)
    assert all(event["metadata"]["report_bridge"] is True for event in events)
    assert all(event["metadata"]["report_company_name"] == "Eli Lilly and Company" for event in events)


def test_report_bridge_skips_disease_reports_without_persisting_events():
    from src.backtest.events_db import get_trusted_events_for_chart
    from src.reports.disease.report_kline_bridge import ReportKlineBridge

    package = _package(profile=_disease_profile())

    result = ReportKlineBridge().run(package)

    assert result == {
        "status": "skipped",
        "skip_reason": "not_company_report",
        "company_name": None,
        "ticker": None,
        "kline_url": None,
        "event_count": 0,
        "inserted_event_count": 0,
    }
    assert get_trusted_events_for_chart("LLY") == []


def test_report_bridge_skips_reports_with_too_little_evidence():
    from src.backtest.events_db import get_trusted_events_for_chart
    from src.reports.disease.report_kline_bridge import ReportKlineBridge

    package = _package(trials=[_trial("NCT00000001")], retained_count=1)

    result = ReportKlineBridge().run(package)

    assert result["status"] == "skipped"
    assert result["skip_reason"] == "insufficient_evidence"
    assert result["event_count"] == 0
    assert get_trusted_events_for_chart("LLY") == []


def test_report_bridge_skips_company_reports_outside_kline_universe():
    from src.backtest.events_db import get_trusted_events_for_chart
    from src.reports.disease.report_kline_bridge import ReportKlineBridge

    package = _package(profile=_company_profile("Unknown Therapeutics"))

    result = ReportKlineBridge().run(package)

    assert result["status"] == "skipped"
    assert result["skip_reason"] == "company_not_in_kline_universe"
    assert result["company_name"] == "Unknown Therapeutics"
    assert result["ticker"] is None
    assert get_trusted_events_for_chart("LLY") == []
