"""Event ingestion service with 6-hour cache freshness."""

from datetime import datetime, timedelta
import os
from typing import Optional
from loguru import logger

from src.backtest.events_db import (
    init_db,
    init_fetch_log_table,
    insert_events,
    get_trusted_events_for_chart,
    record_fetch_attempt,
    get_last_fetch_at,
    get_fetch_log_entries,
)
from src.tools.openfda_client import (
    OpenFDAClient,
    normalize_biotech_events as normalize_openfda,
)
from src.tools.clinical_trials_client import (
    search_trials,
    normalize_clinical_trial_milestone_events,
)
from src.tools.alpha_vantage_news_client import fetch_market_news_events
from src.tools.gdelt_client import fetch_biotech_macro_events
from src.tools.macro_regime_client import fetch_macro_regime_events
from src.kline.event_filter import enrich_event_metadata
from src.kline.event_trust import (
    apply_event_trust,
    build_query_hash,
    build_source_run_id,
    decode_metadata,
)
from src.kline.ticker_resolver import TickerResolver


def _is_cache_stale(last_fetch_at: Optional[str], max_age_hours: int) -> bool:
    """Check if last fetch timestamp is older than max_age_hours."""
    if last_fetch_at is None:
        return True

    try:
        last_fetch = datetime.fromisoformat(last_fetch_at)
        age = datetime.now() - last_fetch
        return age > timedelta(hours=max_age_hours)
    except (ValueError, TypeError):
        return True


def get_source_statuses_for_ticker(ticker: str) -> list[dict]:
    """Return cached source fetch statuses for a ticker."""
    init_fetch_log_table()
    return get_fetch_log_entries(ticker)


def get_cached_events_for_ticker(ticker: str, max_age_hours: int = 6) -> list[dict]:
    """Return trusted cached chart events without fetching external sources."""
    init_db()
    init_fetch_log_table()
    return get_trusted_events_for_chart(ticker)


def _status_for_exception(exc: Exception) -> str:
    """Map source fetch exceptions into user-facing data-source states."""
    text = str(exc).lower()
    if "429" in text or "too many requests" in text or "rate" in text:
        return "rate_limited"
    return "error"


def _source_cache_is_stale(
    source: str,
    last_fetch_at: Optional[str],
    cached_status: str | None,
    max_age_hours: int,
) -> bool:
    if _is_cache_stale(last_fetch_at, max_age_hours):
        return True
    if (
        source == "alphavantage"
        and cached_status == "disabled"
        and os.getenv("ALPHA_VANTAGE_API_KEY")
    ):
        return True
    return False


def _cached_source_statuses(ticker: str) -> dict[str, str | None]:
    return {
        str(row.get("source")): row.get("status")
        for row in get_fetch_log_entries(ticker)
        if isinstance(row, dict) and row.get("source")
    }


def _company_identity(ticker: str) -> str:
    """Return a stable ticker/company identity string for trust metadata."""
    normalized_ticker = str(ticker or "").strip().upper() or "UNKNOWN"
    try:
        company = TickerResolver().resolve(normalized_ticker)
    except ValueError:
        return f"{normalized_ticker}|{normalized_ticker}"
    return f"{company.ticker}|{company.name}"


_CLINICAL_OWNERSHIP_EVIDENCE_TOKENS = frozenset(
    {
        "sponsor",
        "collaborator",
        "sponsor_alias",
        "collaborator_alias",
        "company_alias",
    }
)


def _ownership_for_event(
    event: dict,
    source: str,
) -> tuple[str, str, str | None]:
    """Classify event ownership for trust-boundary persistence."""
    source_key = str(source or event.get("source") or "").strip().lower()
    if source_key == "clinicaltrials":
        metadata = decode_metadata(event.get("metadata"))
        ownership_status = str(metadata.get("ownership_status") or "").strip().lower()
        raw_entity_match = metadata.get("entity_match")
        quarantine_reason = metadata.get("quarantine_reason")
        if ownership_status == "owned":
            if raw_entity_match is None:
                return (
                    "unknown",
                    "quarantined",
                    quarantine_reason or "missing clinical ownership evidence",
                )
            if not isinstance(raw_entity_match, str):
                return (
                    "unknown",
                    "quarantined",
                    quarantine_reason or "malformed clinical ownership evidence",
                )
            entity_match = raw_entity_match.strip().lower()
            if entity_match in _CLINICAL_OWNERSHIP_EVIDENCE_TOKENS:
                return ("owned", "trusted", None)
            if entity_match in {"", "unknown", "unowned"}:
                return (
                    "unknown",
                    "quarantined",
                    quarantine_reason or "missing clinical ownership evidence",
                )
            return (
                "unknown",
                "quarantined",
                quarantine_reason or "malformed clinical ownership evidence",
            )
        if ownership_status == "unowned":
            return (
                "unowned",
                "quarantined",
                quarantine_reason
                or "clinical trial sponsor/collaborator did not match requested ticker",
            )
        return (
            "unknown",
            "quarantined",
            quarantine_reason or "missing clinical ownership evidence",
        )
    if source_key == "macro_regime":
        return ("macro_context", "trusted", None)
    if source_key in {"openfda", "alphavantage", "gdelt"}:
        return ("market_relevant", "trusted", None)
    return ("unknown", "quarantined", "unknown event source")


def _enrich_events(
    events: list[dict],
    *,
    ticker: str,
    source: str,
    source_run_id: str,
    query_hash: str,
) -> list[dict]:
    """Apply phase2 event taxonomy/scoring and trust metadata before persistence."""
    company_identity = _company_identity(ticker)
    enriched_events = []
    for event in events:
        enriched = enrich_event_metadata(event)
        ownership_status, trust_status, quarantine_reason = _ownership_for_event(
            enriched,
            source,
        )
        enriched_events.append(
            apply_event_trust(
                enriched,
                ticker=ticker,
                source=source,
                source_run_id=source_run_id,
                query_hash=query_hash,
                company_identity=company_identity,
                ownership_status=ownership_status,
                trust_status=trust_status,
                quarantine_reason=quarantine_reason,
            )
        )
    return enriched_events


def get_events_for_ticker(ticker: str, max_age_hours: int = 6) -> list[dict]:
    """
    Fetch and cache biotech events for a ticker with 6-hour freshness.

    Orchestrates event fetching from openFDA and ClinicalTrials with cache logic:
    - Initialize DB tables on first call
    - Query sources only if cache is stale (> max_age_hours old)
    - Normalize results using source-specific helpers
    - Insert events into biotech_events table
    - Record fetch attempt even for zero-result responses
    - Return all events for the ticker

    Args:
        ticker: Stock ticker symbol (e.g., "MRNA")
        max_age_hours: Cache freshness threshold in hours (default: 6)

    Returns:
        List of event dictionaries matching BiotechEvent interface
    """
    # Initialize DB tables
    init_db()
    init_fetch_log_table()

    sources = ["openfda", "clinicaltrials", "alphavantage", "gdelt", "macro_regime"]
    source_statuses = _cached_source_statuses(ticker)

    for source in sources:
        last_fetch = get_last_fetch_at(ticker, source)
        cached_status = source_statuses.get(source)

        if not _source_cache_is_stale(source, last_fetch, cached_status, max_age_hours):
            logger.info(f"Cache hit for {ticker}/{source} (age < {max_age_hours}h)")
            continue

        logger.info(f"Fetching {source} for {ticker} (cache stale or missing)")

        try:
            if source == "openfda":
                source_run_id = build_source_run_id(ticker, source)
                query_hash = build_query_hash(source, ticker, {"limit": 20})
                client = OpenFDAClient(raise_on_error=True)
                payload = client.collect(ticker, limit=20)

                # Normalize all three slices
                events = []
                for slice_name in ["label", "event", "drugsfda"]:
                    slice_payload = payload.get(slice_name, {})
                    if slice_payload and slice_payload.get("results"):
                        events.extend(
                            normalize_openfda(
                                slice_payload,
                                source="openfda",
                                requested_ticker=ticker,
                            )
                        )

                events = _enrich_events(
                    events,
                    ticker=ticker,
                    source=source,
                    source_run_id=source_run_id,
                    query_hash=query_hash,
                )
                item_count = len(events)
                if events:
                    insert_events(events)
                    logger.info(f"Inserted {item_count} openFDA events for {ticker}")

                record_fetch_attempt(
                    ticker,
                    source,
                    item_count,
                    status="ready" if item_count > 0 else "empty",
                )

            elif source == "clinicaltrials":
                source_run_id = build_source_run_id(ticker, source)
                query_hash = build_query_hash(source, ticker, {"max_results": 50})
                trials = search_trials(
                    ticker,
                    max_results=50,
                    raise_on_error=True,
                )
                events = normalize_clinical_trial_milestone_events(
                    trials,
                    source="clinicaltrials",
                    requested_ticker=ticker,
                    include_unowned=True,
                )

                events = _enrich_events(
                    events,
                    ticker=ticker,
                    source=source,
                    source_run_id=source_run_id,
                    query_hash=query_hash,
                )
                item_count = len(events)
                if events:
                    insert_events(events)
                    logger.info(
                        f"Inserted {item_count} ClinicalTrials events for {ticker}"
                    )

                record_fetch_attempt(
                    ticker,
                    source,
                    item_count,
                    status="ready" if item_count > 0 else "empty",
                )

            elif source == "alphavantage":
                source_run_id = build_source_run_id(ticker, source)
                query_hash = build_query_hash(source, ticker)
                events, source_status = fetch_market_news_events(ticker)

                events = _enrich_events(
                    events,
                    ticker=ticker,
                    source=source,
                    source_run_id=source_run_id,
                    query_hash=query_hash,
                )
                item_count = len(events)
                if events:
                    insert_events(events)
                    logger.info(
                        f"Inserted {item_count} Alpha Vantage news events for {ticker}"
                    )

                record_fetch_attempt(
                    ticker,
                    source,
                    item_count,
                    status=source_status.get("status"),
                    message=source_status.get("message"),
                )

            elif source == "gdelt":
                source_run_id = build_source_run_id(ticker, source)
                query_hash = build_query_hash(source, ticker, {"max_records": 20})
                events = fetch_biotech_macro_events(
                    ticker,
                    max_records=20,
                    raise_on_error=True,
                )

                events = _enrich_events(
                    events,
                    ticker=ticker,
                    source=source,
                    source_run_id=source_run_id,
                    query_hash=query_hash,
                )
                item_count = len(events)
                if events:
                    insert_events(events)
                    logger.info(f"Inserted {item_count} GDELT events for {ticker}")

                record_fetch_attempt(
                    ticker,
                    source,
                    item_count,
                    status="ready" if item_count > 0 else "empty",
                )

            elif source == "macro_regime":
                source_run_id = build_source_run_id(ticker, source)
                query_hash = build_query_hash(source, ticker)
                events = fetch_macro_regime_events(ticker)

                events = _enrich_events(
                    events,
                    ticker=ticker,
                    source=source,
                    source_run_id=source_run_id,
                    query_hash=query_hash,
                )
                item_count = len(events)
                if events:
                    insert_events(events)
                    logger.info(
                        f"Inserted {item_count} macro regime events for {ticker}"
                    )

                record_fetch_attempt(
                    ticker,
                    source,
                    item_count,
                    status="ready" if item_count > 0 else "empty",
                )

        except Exception as e:
            logger.error(f"Error fetching {source} for {ticker}: {e}")
            record_fetch_attempt(
                ticker,
                source,
                0,
                status=_status_for_exception(e),
                message=str(e),
            )

    # Return only trusted projections for the ticker.
    return get_trusted_events_for_chart(ticker)
