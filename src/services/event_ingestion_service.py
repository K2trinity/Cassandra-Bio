"""Event ingestion service with 6-hour cache freshness."""

from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

from src.backtest.events_db import (
    init_db,
    init_fetch_log_table,
    insert_events,
    get_events_for_chart,
    record_fetch_attempt,
    get_last_fetch_at,
    get_fetch_log_entries,
)
from src.tools.openfda_client import OpenFDAClient, normalize_biotech_events as normalize_openfda
from src.tools.clinical_trials_client import search_trials, normalize_biotech_events as normalize_clinical_trials


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


def _status_for_exception(exc: Exception) -> str:
    """Map source fetch exceptions into user-facing data-source states."""
    text = str(exc).lower()
    if "429" in text or "too many requests" in text or "rate" in text:
        return "rate_limited"
    return "error"


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

    sources = ["openfda", "clinicaltrials"]

    for source in sources:
        last_fetch = get_last_fetch_at(ticker, source)

        if not _is_cache_stale(last_fetch, max_age_hours):
            logger.info(f"Cache hit for {ticker}/{source} (age < {max_age_hours}h)")
            continue

        logger.info(f"Fetching {source} for {ticker} (cache stale or missing)")

        try:
            if source == "openfda":
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
                trials = search_trials(
                    ticker,
                    max_results=50,
                    raise_on_error=True,
                )
                events = normalize_clinical_trials(
                    trials,
                    source="clinicaltrials",
                    requested_ticker=ticker,
                )

                item_count = len(events)
                if events:
                    insert_events(events)
                    logger.info(f"Inserted {item_count} ClinicalTrials events for {ticker}")

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

    # Return all events for the ticker
    return get_events_for_chart(ticker)
