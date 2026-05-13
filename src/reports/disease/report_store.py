from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from src.backtest import events_db
from src.backtest.migrations import apply_sqlite_migrations


class ReportStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else events_db.DB_PATH

    def save(
        self,
        *,
        package: Any,
        narratives: Any,
        artifact_paths: dict[str, Any],
        query: str,
        target_type: str,
        target_name: str,
        report_mode: str,
        source_audit: Any,
    ) -> dict[str, Any]:
        package_json = _canonical_json(_jsonable(package))
        narratives_json = _canonical_json(_jsonable(narratives))
        artifact_paths_json = _canonical_json(_jsonable(artifact_paths))
        source_audit_json = _canonical_json(_jsonable(source_audit))
        dedupe_key = _dedupe_key(
            query=query,
            target_type=target_type,
            target_name=target_name,
            report_mode=report_mode,
            package_json=_canonical_json(_stable_for_dedupe(_jsonable(package))),
        )

        apply_sqlite_migrations(self.db_path)
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA busy_timeout = 30000")
            report_id = str(uuid.uuid4())
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO report_documents (
                            report_id,
                            dedupe_key,
                            query,
                            target_type,
                            target_name,
                            report_mode,
                            package_json,
                            narratives_json,
                            artifact_paths_json,
                            source_audit_json,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                        """,
                        (
                            report_id,
                            dedupe_key,
                            query,
                            target_type,
                            target_name,
                            report_mode,
                            package_json,
                            narratives_json,
                            artifact_paths_json,
                            source_audit_json,
                        ),
                    )
                return {
                    "status": "inserted",
                    "report_id": report_id,
                    "inserted": True,
                    "updated": False,
                    "dedupe_key": dedupe_key,
                }
            except sqlite3.IntegrityError:
                with conn:
                    conn.execute(
                        """
                        UPDATE report_documents
                        SET
                            package_json = ?,
                            narratives_json = ?,
                            artifact_paths_json = ?,
                            source_audit_json = ?,
                            updated_at = datetime('now')
                        WHERE dedupe_key = ?
                        """,
                        (
                            package_json,
                            narratives_json,
                            artifact_paths_json,
                            source_audit_json,
                            dedupe_key,
                        ),
                    )
                row = conn.execute(
                    """
                    SELECT report_id
                    FROM report_documents
                    WHERE dedupe_key = ?
                    """,
                    (dedupe_key,),
                ).fetchone()
                return {
                    "status": "duplicate",
                    "report_id": row[0] if row else None,
                    "inserted": False,
                    "updated": True,
                    "dedupe_key": dedupe_key,
                }
        finally:
            conn.close()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _stable_for_dedupe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _stable_for_dedupe(item)
            for key, item in value.items()
            if key != "generated_at"
        }
    if isinstance(value, list):
        return [_stable_for_dedupe(item) for item in value]
    return value


def _dedupe_key(
    *,
    query: str,
    target_type: str,
    target_name: str,
    report_mode: str,
    package_json: str,
) -> str:
    payload = _canonical_json(
        {
            "query": query,
            "target_type": target_type,
            "target_name": target_name,
            "report_mode": report_mode,
            "package_json": package_json,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["ReportStore"]
