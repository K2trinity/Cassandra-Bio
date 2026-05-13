from __future__ import annotations

from datetime import date
from typing import Any

from src.backtest import events_db
from src.kline.event_filter import enrich_event_metadata
from src.kline.event_trust import (
    apply_event_trust,
    build_query_hash,
    build_source_run_id,
)
from src.kline.ticker_resolver import TickerResolver
from src.reports.disease.models import ClinicalTrialRecord, DiseaseReportPackage
from src.tools.clinical_trials_client import normalize_clinical_trial_milestone_events


BRIDGE_SOURCE = "clinicaltrials"
MIN_RETAINED_RECORDS = 3


class ReportKlineBridge:
    """Persist company report trial milestones into the K-line trusted event store."""

    def __init__(
        self,
        *,
        resolver: TickerResolver | None = None,
        min_retained_records: int = MIN_RETAINED_RECORDS,
    ) -> None:
        self.resolver = resolver or TickerResolver()
        self.min_retained_records = max(1, int(min_retained_records))

    def run(
        self,
        package: DiseaseReportPackage | dict[str, Any] | None,
        *,
        report_path: str | None = None,
    ) -> dict[str, Any]:
        report_package = _coerce_package(package)
        if report_package is None:
            return _skipped("missing_package")

        profile = report_package.disease_profile
        if profile.target_type != "company":
            return _skipped("not_company_report")

        company_name = profile.company_name or profile.target_name
        if not company_name:
            return _skipped("missing_company_name")

        retained_count = int(report_package.source_audit.retained_count or 0)
        trial_count = len(report_package.clinical_trials)
        if retained_count < self.min_retained_records or trial_count < self.min_retained_records:
            return _skipped(
                "insufficient_evidence",
                company_name=company_name,
            )

        company = self.resolver.resolve_company_in_universe(company_name)
        if company is None:
            return _skipped(
                "company_not_in_kline_universe",
                company_name=company_name,
            )

        source_run_id = build_source_run_id(company.ticker, "report_bridge")
        query_hash = build_query_hash(
            "report_bridge",
            company.ticker,
            {
                "company_name": company_name,
                "retained_count": retained_count,
                "trial_count": trial_count,
            },
        )
        trial_payloads = [
            _trial_to_milestone_payload(trial)
            for trial in report_package.clinical_trials
        ]
        raw_events = normalize_clinical_trial_milestone_events(
            trial_payloads,
            source=BRIDGE_SOURCE,
            requested_ticker=company.ticker,
            include_unowned=True,
        )
        trusted_events = [
            _trusted_report_event(
                event,
                ticker=company.ticker,
                company_name=company_name,
                report_path=report_path,
                source_run_id=source_run_id,
                query_hash=query_hash,
                company_identity=f"{company.ticker}|{company.name}",
            )
            for event in raw_events
            if _has_required_event_evidence(event)
        ]
        if not trusted_events:
            return _skipped(
                "no_kline_events",
                company_name=company_name,
                ticker=company.ticker,
            )

        events_db.init_db()
        inserted_event_count = events_db.insert_events(trusted_events)
        return {
            "status": "ready",
            "skip_reason": None,
            "company_name": company_name,
            "ticker": company.ticker,
            "kline_url": f"/kline/{company.ticker}",
            "event_count": len(trusted_events),
            "inserted_event_count": inserted_event_count,
        }


def _coerce_package(
    package: DiseaseReportPackage | dict[str, Any] | None,
) -> DiseaseReportPackage | None:
    if isinstance(package, DiseaseReportPackage):
        return package
    if isinstance(package, dict):
        try:
            return DiseaseReportPackage.model_validate(package)
        except Exception:  # noqa: BLE001
            return None
    return None


def _trial_to_milestone_payload(trial: ClinicalTrialRecord) -> dict[str, Any]:
    return {
        "nct_id": trial.nct_number,
        "nct_number": trial.nct_number,
        "title": trial.study_title,
        "status": trial.status,
        "phase": ", ".join(trial.phases),
        "conditions": ", ".join(trial.conditions),
        "interventions": ", ".join(trial.interventions),
        "sponsor": trial.sponsor,
        "has_results": trial.has_results,
        "results_first_posted": _date_text(trial.results_first_posted),
        "primary_completion_date": _date_text(trial.primary_completion_date),
        "completion_date": _date_text(trial.completion_date),
        "last_update_posted": _date_text(trial.last_update_posted),
        "why_stopped": trial.why_stopped,
        "url": trial.source_url,
    }


def _trusted_report_event(
    event: dict[str, Any],
    *,
    ticker: str,
    company_name: str,
    report_path: str | None,
    source_run_id: str,
    query_hash: str,
    company_identity: str,
) -> dict[str, Any]:
    enriched = enrich_event_metadata(event)
    metadata = dict(enriched.get("metadata") or {})
    metadata.update(
        {
            "derived_from_report": True,
            "report_bridge": True,
            "report_company_name": company_name,
            "report_path": report_path,
            "report_target_type": "company",
        }
    )
    enriched["metadata"] = metadata
    return apply_event_trust(
        enriched,
        ticker=ticker,
        source=BRIDGE_SOURCE,
        source_run_id=source_run_id,
        query_hash=query_hash,
        company_identity=company_identity,
        ownership_status="owned",
        trust_status="trusted",
    )


def _has_required_event_evidence(event: dict[str, Any]) -> bool:
    return bool(
        str(event.get("date") or "").strip()
        and event.get("source_ids")
        and str(event.get("source_url") or "").strip()
    )


def _date_text(value: date | str | None) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    if value:
        return str(value)
    return None


def _skipped(
    skip_reason: str,
    *,
    company_name: str | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "skipped",
        "skip_reason": skip_reason,
        "company_name": company_name,
        "ticker": ticker,
        "kline_url": f"/kline/{ticker}" if ticker else None,
        "event_count": 0,
        "inserted_event_count": 0,
    }


__all__ = ["ReportKlineBridge"]
