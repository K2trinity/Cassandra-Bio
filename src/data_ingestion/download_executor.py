from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any

from src.backtest.price_snapshot import append_prices_daily_frame
from src.backtest.research_db import RESEARCH_DIR, initialize_research_database
from src.backtest.snapshot_builder import (
    DataSnapshot,
    build_data_snapshot_id,
    insert_data_snapshot,
)
from src.backtest.universe_builder import (
    BIOTECH_US_UNIVERSE_ID,
    UniverseMember,
    UniverseSourceRow,
    build_universe_snapshot,
)
from src.backtest.universe_catalog import write_universe_snapshot
from src.data_ingestion.checkpoints import (
    IngestionCheckpoint,
    is_completed,
    record_checkpoint,
)
from src.data_ingestion.fmp_client import FmpClient
from src.data_ingestion.fundamentals import (
    normalize_fmp_financial_statements,
    normalize_sec_company_facts,
)
from src.data_ingestion.fundamentals_store import (
    write_fundamentals_rows,
    write_sec_companyfacts_rows,
)
from src.data_ingestion.manifest import build_snapshot_manifest, write_snapshot_manifest
from src.data_ingestion.provider_config import load_provider_config
from src.data_ingestion.provider_log import record_provider_fetch
from src.data_ingestion.provider_result import ProviderResult
from src.data_ingestion.rate_limit import FixedWindowRateLimit, RateLimitDecision
from src.data_ingestion.sec_client import SecClient
from src.data_ingestion.tiingo_client import TiingoClient
from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices

MAX_RUNTIME_LIMIT_SLEEP_SECONDS = 2.0


@dataclass(frozen=True)
class DownloadRequest:
    snapshot_date: str
    start_date: str
    end_date: str
    providers: tuple[str, ...]
    dry_run: bool = True
    resume: bool = True
    limit_tickers: int | None = None
    universe_id: str = BIOTECH_US_UNIVERSE_ID
    research_dir: str | Path = RESEARCH_DIR
    daily_fmp_budget: int = 240

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "providers",
            tuple(_provider_name(provider) for provider in self.providers),
        )


@dataclass(frozen=True)
class DownloadSummary:
    data_snapshot_id: str
    run_id: str
    dry_run: bool
    providers: tuple[str, ...]
    universe_member_count: int
    planned_units: int
    completed_units: int
    skipped_units: int
    failed_units: int
    rate_limited_units: int
    manifest_path: str | None


@dataclass(frozen=True)
class _PlannedUnit:
    provider: str
    phase: str
    ticker: str
    endpoint: str
    period_start: str | None
    period_end: str | None


@dataclass(frozen=True)
class _UnitExecutionResult:
    status: str
    reason: str | None = None


def run_download(
    request: DownloadRequest,
    *,
    universe_rows: Iterable[UniverseSourceRow] | None = None,
    tiingo_client: Any | None = None,
    sec_client: Any | None = None,
    fmp_client: Any | None = None,
    rate_limiters: Mapping[str, Any] | None = None,
) -> DownloadSummary:
    research_dir = Path(request.research_dir)
    db_path = research_dir / "cassandra_research.duckdb"
    initialize_research_database(db_path)

    universe_snapshot = build_universe_snapshot(
        list(universe_rows or []),
        as_of_date=request.snapshot_date,
    )
    selected_members = _limited_members(
        universe_snapshot.members,
        request.limit_tickers,
    )
    data_snapshot_id = _build_snapshot_id(request, universe_snapshot.universe_snapshot_id)
    units = _plan_units(request, selected_members)
    run_id = _build_run_id(
        request,
        universe_snapshot_id=universe_snapshot.universe_snapshot_id,
        selected_members=selected_members,
        units=units,
    )

    if not request.dry_run:
        write_universe_snapshot(universe_snapshot, db_path=db_path)
        insert_data_snapshot(
            _build_data_snapshot(
                request=request,
                data_snapshot_id=data_snapshot_id,
                universe_snapshot_id=universe_snapshot.universe_snapshot_id,
            ),
            db_path=db_path,
        )

    completed_units = 0
    skipped_units = 0
    failed_units = 0
    rate_limited_units = 0
    skipped: list[dict[str, Any]] = []
    fetch_summary: dict[str, dict[str, int]] = {}

    if not request.dry_run:
        tiingo_client, sec_client, fmp_client = _resolve_provider_clients(
            request,
            tiingo_client=tiingo_client,
            sec_client=sec_client,
            fmp_client=fmp_client,
        )
        runtime_limiters = _resolve_rate_limiters(request, rate_limiters)
        _ensure_executable_provider_planned(
            units,
            tiingo_client=tiingo_client,
            sec_client=sec_client,
            fmp_client=fmp_client,
        )
        for unit in units:
            fetch_summary.setdefault(unit.provider, {})
            if unit.provider == "tiingo":
                result = _execute_tiingo_unit(
                    unit,
                    request=request,
                    run_id=run_id,
                    data_snapshot_id=data_snapshot_id,
                    db_path=db_path,
                    client=tiingo_client,
                    rate_limiters=runtime_limiters,
                )
            elif unit.provider == "sec":
                result = _execute_sec_unit(
                    unit,
                    request=request,
                    run_id=run_id,
                    data_snapshot_id=data_snapshot_id,
                    db_path=db_path,
                    client=sec_client,
                    rate_limiters=runtime_limiters,
                )
            elif unit.provider == "fmp":
                result = _execute_fmp_unit(
                    unit,
                    request=request,
                    run_id=run_id,
                    data_snapshot_id=data_snapshot_id,
                    db_path=db_path,
                    client=fmp_client,
                    rate_limiters=runtime_limiters,
                )
            else:
                result = _skip_stubbed_unit(
                    unit,
                    request=request,
                    run_id=run_id,
                    data_snapshot_id=data_snapshot_id,
                    db_path=db_path,
                    client=sec_client if unit.provider == "sec" else fmp_client,
                )

            fetch_summary[unit.provider][result.status] = (
                fetch_summary[unit.provider].get(result.status, 0) + 1
            )
            if result.status == "success":
                completed_units += 1
            elif result.status == "skipped":
                skipped_units += 1
                skipped.append(_unit_payload(unit, reason=result.reason or "skipped"))
            elif result.status == "rate_limited":
                rate_limited_units += 1
            else:
                failed_units += 1

    manifest = build_snapshot_manifest(
        data_snapshot_id=data_snapshot_id,
        snapshot_date=request.snapshot_date,
        universe_id=request.universe_id,
        providers=request.providers,
        universe_member_count=len(universe_snapshot.members),
        coverage={
            "prices": {
                "tickers": len(
                    {unit.ticker for unit in units if unit.provider == "tiingo"}
                )
            },
            "planned_units": len(units),
            "selected_tickers": [member.ticker for member in selected_members],
            "phases": sorted({unit.phase for unit in units}),
            "endpoints": [unit.endpoint for unit in units],
        },
        fetch_summary=fetch_summary,
        skipped=skipped,
        source_hashes={
            "universe": _stable_hash(universe_snapshot.universe_snapshot_id),
            "events": _stable_hash("no-events"),
        },
        metadata={
            "dry_run": request.dry_run,
            "run_id": run_id,
            "universe_snapshot_id": universe_snapshot.universe_snapshot_id,
            "execution_plan": {
                "date_range": {
                    "start_date": request.start_date,
                    "end_date": request.end_date,
                },
                "planned_units": len(units),
                "selected_tickers": [member.ticker for member in selected_members],
                "phases": sorted({unit.phase for unit in units}),
                "endpoints": [unit.endpoint for unit in units],
            },
        },
    )
    manifest_path = write_snapshot_manifest(
        manifest,
        output_dir=research_dir / "manifests" / run_id,
    )

    return DownloadSummary(
        data_snapshot_id=data_snapshot_id,
        run_id=run_id,
        dry_run=request.dry_run,
        providers=request.providers,
        universe_member_count=len(universe_snapshot.members),
        planned_units=len(units),
        completed_units=completed_units,
        skipped_units=skipped_units,
        failed_units=failed_units,
        rate_limited_units=rate_limited_units,
        manifest_path=str(manifest_path),
    )


def _execute_tiingo_unit(
    unit: _PlannedUnit,
    *,
    request: DownloadRequest,
    run_id: str,
    data_snapshot_id: str,
    db_path: Path,
    client: Any | None,
    rate_limiters: Mapping[str, Any],
) -> _UnitExecutionResult:
    if request.resume and is_completed(
        db_path=db_path,
        run_id=run_id,
        provider=unit.provider,
        phase=unit.phase,
        ticker=unit.ticker,
        endpoint=unit.endpoint,
        period_start=unit.period_start,
        period_end=unit.period_end,
    ):
        return _UnitExecutionResult("skipped", "already_completed")

    if client is None:
        _record_checkpoint(
            unit,
            run_id,
            data_snapshot_id,
            db_path,
            "skipped",
            "missing_client",
        )
        return _UnitExecutionResult("skipped", "missing_client")

    result = _fetch_with_runtime_limit(
        provider=unit.provider,
        endpoint=unit.endpoint,
        unit=unit,
        db_path=db_path,
        rate_limiters=rate_limiters,
        metadata={
            "ticker": unit.ticker,
            "period_start": unit.period_start,
            "period_end": unit.period_end,
        },
        fetch=lambda: client.fetch_daily_prices(
            ticker=unit.ticker,
            start_date=request.start_date,
            end_date=request.end_date,
        ),
    )

    if result.status == "success":
        if not result.rows:
            _record_checkpoint(
                unit,
                run_id,
                data_snapshot_id,
                db_path,
                "skipped",
                "no_rows",
            )
            return _UnitExecutionResult("skipped", "no_rows")
        try:
            frame = normalize_tiingo_eod_prices(
                result.rows,
                ticker=unit.ticker,
                data_snapshot_id=data_snapshot_id,
            )
            if frame.empty:
                _record_checkpoint(
                    unit,
                    run_id,
                    data_snapshot_id,
                    db_path,
                    "skipped",
                    "no_valid_rows",
                )
                return _UnitExecutionResult("skipped", "no_valid_rows")
            append_prices_daily_frame(
                frame,
                output_root=Path(request.research_dir) / "prices_daily",
            )
        except Exception as exc:
            _record_checkpoint(
                unit,
                run_id,
                data_snapshot_id,
                db_path,
                "failed",
                str(exc),
            )
            return _UnitExecutionResult("failed", str(exc))

        _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "success", None)
        return _UnitExecutionResult("success")

    if result.status == "rate_limited":
        _record_checkpoint(
            unit,
            run_id,
            data_snapshot_id,
            db_path,
            "rate_limited",
            result.message,
        )
        return _UnitExecutionResult("rate_limited", result.message)

    _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "failed", result.message)
    return _UnitExecutionResult("failed", result.message)


def _execute_sec_unit(
    unit: _PlannedUnit,
    *,
    request: DownloadRequest,
    run_id: str,
    data_snapshot_id: str,
    db_path: Path,
    client: Any | None,
    rate_limiters: Mapping[str, Any],
) -> _UnitExecutionResult:
    if request.resume and is_completed(
        db_path=db_path,
        run_id=run_id,
        provider=unit.provider,
        phase=unit.phase,
        ticker=unit.ticker,
        endpoint=unit.endpoint,
        period_start=unit.period_start,
        period_end=unit.period_end,
    ):
        return _UnitExecutionResult("skipped", "already_completed")

    if client is None:
        _record_checkpoint(
            unit,
            run_id,
            data_snapshot_id,
            db_path,
            "skipped",
            "missing_client",
        )
        return _UnitExecutionResult("skipped", "missing_client")

    cik = unit.endpoint.rsplit("/", 1)[-1]
    submissions = _fetch_with_runtime_limit(
        provider="sec",
        endpoint=f"/sec/submissions/{cik}",
        unit=unit,
        db_path=db_path,
        rate_limiters=rate_limiters,
        metadata={"ticker": unit.ticker, "cik": cik},
        fetch=lambda: client.fetch_submissions(cik),
    )
    early = _early_result_from_provider_status(
        submissions,
        unit,
        run_id=run_id,
        data_snapshot_id=data_snapshot_id,
        db_path=db_path,
        no_data_message="submissions_not_found",
    )
    if early is not None:
        return early

    companyfacts = _fetch_with_runtime_limit(
        provider="sec",
        endpoint=unit.endpoint,
        unit=unit,
        db_path=db_path,
        rate_limiters=rate_limiters,
        metadata={"ticker": unit.ticker, "cik": cik},
        fetch=lambda: client.fetch_companyfacts(cik),
    )
    early = _early_result_from_provider_status(
        companyfacts,
        unit,
        run_id=run_id,
        data_snapshot_id=data_snapshot_id,
        db_path=db_path,
        no_data_message="companyfacts_not_found",
    )
    if early is not None:
        return early

    if not isinstance(companyfacts.payload, Mapping):
        _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "skipped", "no_data")
        return _UnitExecutionResult("skipped", "no_data")

    try:
        rows = normalize_sec_company_facts(
            cik=cik,
            ticker=unit.ticker,
            companyfacts=companyfacts.payload,
        )
        written = write_sec_companyfacts_rows(
            rows,
            cik=cik,
            ticker=unit.ticker,
            db_path=db_path,
        )
    except Exception as exc:
        _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "failed", str(exc))
        return _UnitExecutionResult("failed", str(exc))

    if written == 0:
        _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "skipped", "no_data")
        return _UnitExecutionResult("skipped", "no_data")

    _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "success", None)
    return _UnitExecutionResult("success")


def _execute_fmp_unit(
    unit: _PlannedUnit,
    *,
    request: DownloadRequest,
    run_id: str,
    data_snapshot_id: str,
    db_path: Path,
    client: Any | None,
    rate_limiters: Mapping[str, Any],
) -> _UnitExecutionResult:
    if request.resume and is_completed(
        db_path=db_path,
        run_id=run_id,
        provider=unit.provider,
        phase=unit.phase,
        ticker=unit.ticker,
        endpoint=unit.endpoint,
        period_start=unit.period_start,
        period_end=unit.period_end,
    ):
        return _UnitExecutionResult("skipped", "already_completed")

    if client is None:
        _record_checkpoint(
            unit,
            run_id,
            data_snapshot_id,
            db_path,
            "skipped",
            "missing_client",
        )
        return _UnitExecutionResult("skipped", "missing_client")

    profile = _fetch_with_runtime_limit(
        provider="fmp",
        endpoint=f"/fmp/profile/{unit.ticker}",
        unit=unit,
        db_path=db_path,
        rate_limiters=rate_limiters,
        metadata={"ticker": unit.ticker},
        fetch=lambda: client.fetch_profile(unit.ticker),
    )
    early = _early_result_from_provider_status(
        profile,
        unit,
        run_id=run_id,
        data_snapshot_id=data_snapshot_id,
        db_path=db_path,
        no_data_message="profile_not_found",
    )
    if early is not None:
        return early

    statement_results = []
    for endpoint, fetch in (
        (
            f"/fmp/income-statement/{unit.ticker}",
            lambda: client.fetch_income_statement(unit.ticker),
        ),
        (
            f"/fmp/balance-sheet-statement/{unit.ticker}",
            lambda: client.fetch_balance_sheet(unit.ticker),
        ),
        (
            f"/fmp/cash-flow-statement/{unit.ticker}",
            lambda: client.fetch_cash_flow(unit.ticker),
        ),
    ):
        result = _fetch_with_runtime_limit(
            provider="fmp",
            endpoint=endpoint,
            unit=unit,
            db_path=db_path,
            rate_limiters=rate_limiters,
            metadata={"ticker": unit.ticker},
            fetch=fetch,
        )
        early = _early_result_from_provider_status(
            result,
            unit,
            run_id=run_id,
            data_snapshot_id=data_snapshot_id,
            db_path=db_path,
            no_data_message="statement_not_found",
        )
        if early is not None:
            return early
        statement_results.append(result)

    statements = _merge_fmp_statement_payloads(
        result.payload for result in statement_results
    )
    if not statements:
        _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "skipped", "no_data")
        return _UnitExecutionResult("skipped", "no_data")

    try:
        rows = normalize_fmp_financial_statements(
            ticker=unit.ticker,
            statements=statements,
            source="fmp",
        )
        written = write_fundamentals_rows(
            rows,
            source="fmp",
            ticker=unit.ticker,
            db_path=db_path,
        )
    except Exception as exc:
        _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "failed", str(exc))
        return _UnitExecutionResult("failed", str(exc))

    if written == 0:
        _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "skipped", "no_data")
        return _UnitExecutionResult("skipped", "no_data")

    _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "success", None)
    return _UnitExecutionResult("success")


def _skip_stubbed_unit(
    unit: _PlannedUnit,
    *,
    request: DownloadRequest,
    run_id: str,
    data_snapshot_id: str,
    db_path: Path,
    client: Any | None,
) -> _UnitExecutionResult:
    if request.resume and is_completed(
        db_path=db_path,
        run_id=run_id,
        provider=unit.provider,
        phase=unit.phase,
        ticker=unit.ticker,
        endpoint=unit.endpoint,
        period_start=unit.period_start,
        period_end=unit.period_end,
    ):
        return _UnitExecutionResult("skipped", "already_completed")
    reason = "stub_not_implemented"
    if client is None:
        reason = "missing_client"
    _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "skipped", reason)
    return _UnitExecutionResult("skipped", reason)


def _fetch_with_runtime_limit(
    *,
    provider: str,
    endpoint: str,
    unit: _PlannedUnit,
    db_path: Path,
    rate_limiters: Mapping[str, Any],
    metadata: Mapping[str, Any],
    fetch: Callable[[], ProviderResult],
) -> ProviderResult:
    limiter = rate_limiters.get(_provider_name(provider))
    decision = _allow_provider_request(limiter, provider)
    request_hash = _stable_endpoint_request_hash(unit, endpoint)
    if not decision.allowed:
        result = ProviderResult(
            status="rate_limited",
            request_hash=request_hash,
            message="runtime rate limit exhausted",
            retry_after_seconds=decision.retry_after_seconds,
        )
        _record_provider_result(
            provider=provider,
            endpoint=endpoint,
            result=result,
            metadata=metadata,
            db_path=db_path,
        )
        return result

    try:
        result = fetch()
    except Exception as exc:
        result = ProviderResult(
            status="failed",
            request_hash=request_hash,
            message=str(exc),
        )
    _record_provider_result(
        provider=provider,
        endpoint=endpoint,
        result=result,
        metadata=metadata,
        db_path=db_path,
    )
    return result


def _allow_provider_request(limiter: Any | None, provider: str) -> RateLimitDecision:
    if limiter is None:
        return RateLimitDecision(allowed=True, retry_after_seconds=0.0)
    decision = limiter.allow(provider)
    if decision.allowed:
        return decision
    retry_after = float(decision.retry_after_seconds or 0.0)
    if 0.0 < retry_after <= MAX_RUNTIME_LIMIT_SLEEP_SECONDS:
        time.sleep(retry_after)
        return limiter.allow(provider)
    return decision


def _record_provider_result(
    *,
    provider: str,
    endpoint: str,
    result: ProviderResult,
    metadata: Mapping[str, Any],
    db_path: Path,
) -> None:
    payload = dict(metadata)
    if result.retry_after_seconds is not None:
        payload["retry_after_seconds"] = result.retry_after_seconds
    record_provider_fetch(
        provider=provider,
        endpoint=endpoint,
        request_hash=result.request_hash,
        status=result.status,
        message=result.message,
        metadata=payload,
        db_path=db_path,
    )


def _early_result_from_provider_status(
    result: ProviderResult,
    unit: _PlannedUnit,
    *,
    run_id: str,
    data_snapshot_id: str,
    db_path: Path,
    no_data_message: str,
) -> _UnitExecutionResult | None:
    if result.status == "success":
        return None
    if result.status == "rate_limited":
        _record_checkpoint(
            unit,
            run_id,
            data_snapshot_id,
            db_path,
            "rate_limited",
            result.message,
        )
        return _UnitExecutionResult("rate_limited", result.message)
    if result.status == "not_found":
        _record_checkpoint(
            unit,
            run_id,
            data_snapshot_id,
            db_path,
            "skipped",
            no_data_message,
        )
        return _UnitExecutionResult("skipped", no_data_message)
    message = result.message or result.status
    _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "failed", message)
    return _UnitExecutionResult("failed", message)


def _merge_fmp_statement_payloads(payloads: Iterable[Any]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for payload in payloads:
        for row in _payload_rows(payload):
            key = _fmp_statement_key(row)
            current = merged.setdefault(key, {})
            current.update(row)
    return list(merged.values())


def _payload_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        return [dict(payload)]
    return []


def _fmp_statement_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("date") or ""),
        str(row.get("calendarYear") or ""),
        str(row.get("period") or ""),
    )


def _record_checkpoint(
    unit: _PlannedUnit,
    run_id: str,
    data_snapshot_id: str,
    db_path: Path,
    status: str,
    last_error: str | None,
) -> None:
    record_checkpoint(
        IngestionCheckpoint(
            run_id=run_id,
            data_snapshot_id=data_snapshot_id,
            provider=unit.provider,
            phase=unit.phase,
            ticker=unit.ticker,
            endpoint=unit.endpoint,
            period_start=unit.period_start,
            period_end=unit.period_end,
            status=status,
            attempt_count=1,
            last_error=last_error,
        ),
        db_path=db_path,
    )


def _plan_units(
    request: DownloadRequest,
    selected_members: Sequence[UniverseMember],
) -> list[_PlannedUnit]:
    units: list[_PlannedUnit] = []
    for provider in request.providers:
        if provider == "tiingo":
            units.extend(_tiingo_unit(member, request) for member in selected_members)
        elif provider in {"nasdaq", "nasdaq_trader"}:
            continue
        elif provider == "sec":
            units.extend(
                _sec_unit(member)
                for member in selected_members
                if member.cik is not None and str(member.cik).strip()
            )
        elif provider == "fmp":
            units.extend(
                _fmp_unit(member, request)
                for member in selected_members
            )
        else:
            raise ValueError(f"unsupported provider: {provider}")
    return units


def _tiingo_unit(member: UniverseMember, request: DownloadRequest) -> _PlannedUnit:
    return _PlannedUnit(
        provider="tiingo",
        phase="prices",
        ticker=member.ticker,
        endpoint=f"/tiingo/daily/{member.ticker}/prices",
        period_start=request.start_date,
        period_end=request.end_date,
    )


def _sec_unit(member: UniverseMember) -> _PlannedUnit:
    return _PlannedUnit(
        provider="sec",
        phase="companyfacts",
        ticker=member.ticker,
        endpoint=f"/sec/companyfacts/{member.cik}",
        period_start=None,
        period_end=None,
    )


def _fmp_unit(member: UniverseMember, request: DownloadRequest) -> _PlannedUnit:
    return _PlannedUnit(
        provider="fmp",
        phase="profile",
        ticker=member.ticker,
        endpoint=f"/fmp/profile/{member.ticker}",
        period_start=request.start_date,
        period_end=request.end_date,
    )


def _limited_members(
    members: Sequence[UniverseMember],
    limit_tickers: int | None,
) -> tuple[UniverseMember, ...]:
    if limit_tickers is None:
        return tuple(members)
    if limit_tickers < 0:
        raise ValueError("limit_tickers must be non-negative")
    return tuple(members[:limit_tickers])


def _build_snapshot_id(request: DownloadRequest, universe_snapshot_id: str) -> str:
    return build_data_snapshot_id(
        snapshot_date=request.snapshot_date,
        price_source=_price_source_token(request.providers),
        universe_id=request.universe_id,
        security_master_hash=_stable_hash(universe_snapshot_id),
        event_snapshot_hash=_stable_hash("no-events"),
    )


def _build_run_id(
    request: DownloadRequest,
    *,
    universe_snapshot_id: str,
    selected_members: Sequence[UniverseMember],
    units: Sequence[_PlannedUnit],
) -> str:
    payload = {
        "date_range": {
            "end_date": request.end_date,
            "start_date": request.start_date,
        },
        "endpoints": sorted({unit.endpoint for unit in units}),
        "phases": sorted({unit.phase for unit in units}),
        "providers": sorted(set(request.providers)),
        "selected_tickers": [member.ticker for member in selected_members],
        "snapshot_date": request.snapshot_date,
        "universe_snapshot_id": universe_snapshot_id,
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"run_{request.snapshot_date.replace('-', '')}_{digest}"


def _build_data_snapshot(
    *,
    request: DownloadRequest,
    data_snapshot_id: str,
    universe_snapshot_id: str,
) -> DataSnapshot:
    return DataSnapshot(
        data_snapshot_id=data_snapshot_id,
        snapshot_date=request.snapshot_date,
        price_source=_price_source_token(request.providers),
        event_source_db="none",
        universe_id=request.universe_id,
        bias_profile="current_constituents_only",
        price_partition_root=str(Path(request.research_dir) / "prices_daily"),
        event_snapshot_hash=_stable_hash("no-events"),
        security_master_hash=_stable_hash(universe_snapshot_id),
        coverage={
            "universe_snapshot_id": universe_snapshot_id,
        },
    )


def _resolve_provider_clients(
    request: DownloadRequest,
    *,
    tiingo_client: Any | None,
    sec_client: Any | None,
    fmp_client: Any | None,
) -> tuple[Any | None, Any | None, Any | None]:
    config = load_provider_config()
    requested = set(request.providers)

    if tiingo_client is None and "tiingo" in requested:
        if config.tiingo_api_key:
            tiingo_client = TiingoClient(config.tiingo_api_key)
        elif _only_requested_provider(request, "tiingo"):
            raise RuntimeError(_missing_credentials_message("tiingo"))

    if sec_client is None and "sec" in requested:
        if config.sec_user_agent:
            sec_client = SecClient(config.sec_user_agent)
        elif _only_requested_provider(request, "sec"):
            raise RuntimeError(_missing_credentials_message("sec"))

    if fmp_client is None and "fmp" in requested:
        if config.fmp_api_key:
            fmp_client = FmpClient(config.fmp_api_key)
        elif _only_requested_provider(request, "fmp"):
            raise RuntimeError(_missing_credentials_message("fmp"))

    return tiingo_client, sec_client, fmp_client


class _ExhaustedRateLimit:
    def allow(self, provider: str) -> RateLimitDecision:
        return RateLimitDecision(allowed=False, retry_after_seconds=86400.0)


def _resolve_rate_limiters(
    request: DownloadRequest,
    rate_limiters: Mapping[str, Any] | None,
) -> dict[str, Any]:
    resolved: dict[str, Any] = {
        "sec": FixedWindowRateLimit(max_requests=8, window_seconds=1.0),
        "fmp": (
            FixedWindowRateLimit(
                max_requests=request.daily_fmp_budget,
                window_seconds=86400.0,
            )
            if request.daily_fmp_budget > 0
            else _ExhaustedRateLimit()
        ),
        "nasdaq": FixedWindowRateLimit(max_requests=1, window_seconds=1.0),
        "nasdaq_trader": FixedWindowRateLimit(max_requests=1, window_seconds=1.0),
        "tiingo": FixedWindowRateLimit(max_requests=5, window_seconds=1.0),
    }
    for provider, limiter in dict(rate_limiters or {}).items():
        resolved[_provider_name(provider)] = limiter
    return resolved


def _ensure_executable_provider_planned(
    units: Sequence[_PlannedUnit],
    *,
    tiingo_client: Any | None,
    sec_client: Any | None,
    fmp_client: Any | None,
) -> None:
    credentialed_units = [
        unit for unit in units if unit.provider in {"tiingo", "sec", "fmp"}
    ]
    if not credentialed_units:
        return
    if any(
        _provider_client_executable(
            provider,
            tiingo_client=tiingo_client,
            sec_client=sec_client,
            fmp_client=fmp_client,
        )
        for provider in {unit.provider for unit in credentialed_units}
    ):
        return
    providers = ", ".join(sorted({unit.provider for unit in credentialed_units}))
    raise RuntimeError(
        "Cannot run download because planned providers have no executable provider "
        f"available ({providers}). Configure credentials for an implemented provider "
        "or use --dry-run."
    )


def _provider_client_executable(
    provider: str,
    *,
    tiingo_client: Any | None,
    sec_client: Any | None,
    fmp_client: Any | None,
) -> bool:
    if provider == "tiingo":
        return _has_methods(tiingo_client, ("fetch_daily_prices",))
    if provider == "sec":
        return _has_methods(sec_client, ("fetch_submissions", "fetch_companyfacts"))
    if provider == "fmp":
        return _has_methods(
            fmp_client,
            (
                "fetch_profile",
                "fetch_income_statement",
                "fetch_balance_sheet",
                "fetch_cash_flow",
            ),
        )
    return False


def _has_methods(client: Any | None, method_names: Sequence[str]) -> bool:
    return client is not None and all(
        callable(getattr(client, name, None)) for name in method_names
    )


def _only_requested_provider(request: DownloadRequest, provider: str) -> bool:
    return set(request.providers) == {provider}


def _missing_credentials_message(provider: str) -> str:
    return (
        f"Cannot run provider '{provider}' because required credentials are not "
        "configured. Use --dry-run or configure credentials outside tracked files."
    )


def _price_source_token(providers: Sequence[str]) -> str:
    normalized = tuple(_provider_name(provider) for provider in providers)
    if "tiingo" in normalized:
        return "tiingo"
    return "+".join(normalized) if normalized else "none"


def _provider_name(provider: str) -> str:
    name = str(provider).strip().lower()
    if not name:
        raise ValueError("provider must be non-empty")
    return name


def _unit_payload(unit: _PlannedUnit, *, reason: str) -> dict[str, Any]:
    return {
        "provider": unit.provider,
        "phase": unit.phase,
        "ticker": unit.ticker,
        "endpoint": unit.endpoint,
        "reason": reason,
    }


def _stable_hash(value: str) -> str:
    return sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _stable_request_hash(unit: _PlannedUnit) -> str:
    payload = {
        "endpoint": unit.endpoint,
        "period_end": unit.period_end,
        "period_start": unit.period_start,
        "provider": unit.provider,
        "ticker": unit.ticker,
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"req_{digest}"


def _stable_endpoint_request_hash(unit: _PlannedUnit, endpoint: str) -> str:
    payload = {
        "endpoint": endpoint,
        "period_end": unit.period_end,
        "period_start": unit.period_start,
        "provider": unit.provider,
        "ticker": unit.ticker,
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"req_{digest}"
