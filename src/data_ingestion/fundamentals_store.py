from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
import math
from pathlib import Path
from typing import Any

from src.backtest.research_db import RESEARCH_DB_PATH, initialize_research_database


def write_fundamentals_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    source: str,
    ticker: str,
    db_path: str | Path | None = None,
) -> int:
    normalized_source = _normalize_source(source)
    normalized_ticker = _normalize_ticker(ticker)
    payloads = _canonicalize_fundamentals_rows(rows)
    if not payloads:
        return 0

    path = initialize_research_database(db_path or RESEARCH_DB_PATH)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            """
            DELETE FROM fundamentals_normalized
            WHERE source = ? AND ticker = ?
            """,
            [normalized_source, normalized_ticker],
        )
        for row in payloads:
            conn.execute(
                """
                INSERT INTO fundamentals_normalized (
                    security_id,
                    ticker,
                    fiscal_period,
                    filing_date,
                    source,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    str(row.get("security_id") or ""),
                    normalized_ticker,
                    str(row.get("fiscal_period") or ""),
                    row.get("filing_date") or row.get("filed"),
                    normalized_source,
                    json.dumps(
                        row,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                ],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return len(payloads)


def write_sec_companyfacts_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    cik: str,
    ticker: str,
    db_path: str | Path | None = None,
) -> int:
    normalized_cik = _normalize_cik(cik)
    normalized_ticker = _normalize_ticker(ticker)
    payloads = _canonicalize_sec_companyfacts_rows(rows)
    if not payloads:
        return 0

    path = initialize_research_database(db_path or RESEARCH_DB_PATH)

    import duckdb

    conn = duckdb.connect(str(path))
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            """
            DELETE FROM sec_companyfacts_normalized
            WHERE cik = ? AND ticker = ?
            """,
            [normalized_cik, normalized_ticker],
        )
        for row in payloads:
            conn.execute(
                """
                INSERT INTO sec_companyfacts_normalized (
                    security_id,
                    ticker,
                    cik,
                    taxonomy,
                    concept,
                    unit,
                    fiscal_year,
                    fiscal_period,
                    form,
                    filed,
                    period_end,
                    value,
                    source,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    row["security_id"],
                    normalized_ticker,
                    normalized_cik,
                    row["taxonomy"],
                    row["concept"],
                    row["unit"],
                    row["fiscal_year"],
                    row["fiscal_period"],
                    row["form"],
                    row["filed"],
                    row["period_end"],
                    row["value"],
                    row["source"],
                ],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return len(payloads)


def _canonicalize_fundamentals_rows(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    payloads = []
    for row_index, row in enumerate(rows):
        payload = {
            str(key): _canonical_json_value(value, row_index=row_index, field=str(key))
            for key, value in dict(row).items()
        }
        for field in ("security_id", "fiscal_period"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"fundamentals row {row_index} missing non-empty {field}."
                )
            payload[field] = value.strip()
        for field in ("filing_date", "filed"):
            if field in payload and payload[field] is not None:
                payload[field] = _canonical_date_value(
                    payload[field],
                    row_index=row_index,
                    field=field,
                )
        payloads.append(payload)
    return payloads


def _canonicalize_sec_companyfacts_rows(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    payloads = []
    for row_index, row in enumerate(rows):
        payload = {
            str(key): _canonical_json_value(value, row_index=row_index, field=str(key))
            for key, value in dict(row).items()
        }
        for field in (
            "security_id",
            "taxonomy",
            "concept",
            "unit",
            "fiscal_period",
            "form",
            "source",
        ):
            value = payload.get(field)
            if not isinstance(value, str):
                raise ValueError(f"SEC companyfacts row {row_index} missing {field}.")
            payload[field] = value.strip()
        fiscal_year = payload.get("fiscal_year")
        try:
            payload["fiscal_year"] = int(fiscal_year)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"SEC companyfacts row {row_index} field fiscal_year must be an integer."
            ) from exc
        try:
            payload["value"] = float(payload.get("value"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"SEC companyfacts row {row_index} field value must be numeric."
            ) from exc
        if not math.isfinite(payload["value"]):
            raise ValueError(
                f"SEC companyfacts row {row_index} field value must be finite."
            )
        for field in ("filed", "period_end"):
            value = payload.get(field)
            payload[field] = (
                _canonical_date_value(value, row_index=row_index, field=field)
                if value
                else None
            )
        payloads.append(payload)
    return payloads


def _canonical_json_value(value: Any, *, row_index: int, field: str) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(
                nested_value,
                row_index=row_index,
                field=f"{field}.{key}",
            )
            for key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [
            _canonical_json_value(
                item,
                row_index=row_index,
                field=f"{field}[{index}]",
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, tuple):
        return [
            _canonical_json_value(
                item,
                row_index=row_index,
                field=f"{field}[{index}]",
            )
            for index, item in enumerate(value)
        ]
    if _is_missing_scalar(value):
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(
                f"fundamentals row {row_index} field {field} must be finite."
            )
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime):
            return value.date().isoformat()
        return value.isoformat()

    numpy_scalar = _numpy_scalar_to_python(value)
    if numpy_scalar is not value:
        return _canonical_json_value(
            numpy_scalar,
            row_index=row_index,
            field=field,
        )

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"fundamentals row {row_index} field {field} must be finite."
            )
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError(
        f"fundamentals row {row_index} field {field} must be JSON-serializable."
    )


def _canonical_date_value(value: Any, *, row_index: int, field: str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return stripped
        try:
            return (
                datetime.fromisoformat(stripped.replace("Z", "+00:00"))
                .date()
                .isoformat()
            )
        except ValueError:
            try:
                return date.fromisoformat(stripped).isoformat()
            except ValueError as exc:
                raise ValueError(
                    f"fundamentals row {row_index} field {field} must be an ISO date."
                ) from exc
    raise ValueError(
        f"fundamentals row {row_index} field {field} must be a date or ISO date string."
    )


def _numpy_scalar_to_python(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:
        return value
    if isinstance(value, np.generic):
        return value.item()
    return value


def _is_missing_scalar(value: Any) -> bool:
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        import numpy as np
    except ImportError:
        pass
    else:
        if isinstance(value, np.generic):
            try:
                if np.isnat(value):
                    return True
            except TypeError:
                pass
            try:
                if bool(np.issubdtype(value.dtype, np.floating)) and bool(
                    np.isnan(value)
                ):
                    return True
            except TypeError:
                pass
    try:
        import pandas as pd
    except ImportError:
        return False
    if value is pd.NA or value is pd.NaT:
        return True
    if type(value).__module__.startswith("pandas."):
        try:
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False
    return False


def _normalize_source(source: str) -> str:
    normalized = str(source).strip().lower()
    if not normalized:
        raise ValueError("source must be a non-empty string.")
    return normalized


def _normalize_ticker(ticker: str) -> str:
    normalized = str(ticker).strip().upper()
    if not normalized:
        raise ValueError("ticker must be a non-empty string.")
    return normalized


def _normalize_cik(cik: str) -> str:
    digits = "".join(char for char in str(cik).strip() if char.isdigit())
    if not digits:
        raise ValueError("cik must contain digits.")
    if len(digits) > 10:
        raise ValueError("cik must be at most 10 digits.")
    return digits.zfill(10)
