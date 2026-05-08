from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
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
from src.data_ingestion.manifest import build_snapshot_manifest, write_snapshot_manifest
from src.data_ingestion.provider_config import load_provider_config
from src.data_ingestion.provider_log import record_provider_fetch
from src.data_ingestion.sec_client import SecClient
from src.data_ingestion.tiingo_client import TiingoClient
from src.data_ingestion.tiingo_prices import normalize_tiingo_eod_prices


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

    try:
        result = client.fetch_daily_prices(
            ticker=unit.ticker,
            start_date=request.start_date,
            end_date=request.end_date,
        )
    except Exception as exc:
        request_hash = _stable_request_hash(unit)
        record_provider_fetch(
            provider=unit.provider,
            endpoint=unit.endpoint,
            request_hash=request_hash,
            status="failed",
            message=str(exc),
            metadata={"ticker": unit.ticker},
            db_path=db_path,
        )
        _record_checkpoint(unit, run_id, data_snapshot_id, db_path, "failed", str(exc))
        return _UnitExecutionResult("failed", str(exc))

    record_provider_fetch(
        provider=unit.provider,
        endpoint=unit.endpoint,
        request_hash=result.request_hash,
        status=result.status,
        message=result.message,
        metadata={
            "ticker": unit.ticker,
            "period_start": unit.period_start,
            "period_end": unit.period_end,
            "retry_after_seconds": result.retry_after_seconds,
        },
        db_path=db_path,
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
                for member in selected_members[: max(0, request.daily_fmp_budget)]
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
