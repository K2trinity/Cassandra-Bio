from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import re
from typing import Any

from src.backtest.research_db import RESEARCH_DIR

_SAFE_SNAPSHOT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def build_snapshot_manifest(
    *,
    data_snapshot_id: str,
    snapshot_date: str,
    universe_id: str,
    providers: Sequence[str],
    universe_member_count: int,
    coverage: Mapping[str, Any],
    fetch_summary: Mapping[str, Any],
    skipped: Sequence[Mapping[str, Any]],
    source_hashes: Mapping[str, str],
    metadata: Mapping[str, Any] | None = None,
    secret_values: Sequence[str] = (),
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "data_snapshot_id": _safe_snapshot_id(data_snapshot_id),
        "snapshot_date": _require_text(snapshot_date, "snapshot_date"),
        "universe_id": _require_text(universe_id, "universe_id"),
        "universe_bias_status": "current_constituents_only",
        "survivorship_bias_warning": True,
        "providers": sorted(
            {_require_text(provider, "provider").lower() for provider in providers}
        ),
        "universe_member_count": int(universe_member_count),
        "coverage": dict(coverage),
        "fetch_summary": dict(fetch_summary),
        "skipped": list(skipped),
        "source_hashes": dict(source_hashes),
        "metadata": dict(metadata or {}),
    }
    return json.loads(_redacted_json(payload, secret_values))


def write_snapshot_manifest(
    manifest: Mapping[str, Any],
    *,
    output_dir: str | Path | None = None,
) -> Path:
    snapshot_id = _safe_snapshot_id(str(manifest["data_snapshot_id"]))
    root = Path(output_dir) if output_dir is not None else RESEARCH_DIR / "manifests"
    root.mkdir(parents=True, exist_ok=True)

    path = root / f"{snapshot_id}-manifest.json"
    tmp_path = path.with_name(f".{path.name}.tmp")
    content = json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False)
    tmp_path.write_text(f"{content}\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def _redacted_json(value: Mapping[str, Any], secret_values: Sequence[str]) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for secret in secret_values:
        if secret:
            text = text.replace(str(secret), "<redacted>")
    return text


def _safe_snapshot_id(value: str) -> str:
    text = _require_text(value, "data_snapshot_id")
    if ".." in text or not _SAFE_SNAPSHOT_ID_PATTERN.fullmatch(text):
        raise ValueError(
            "data_snapshot_id must use only letters, digits, underscores, dots, "
            "and hyphens, with no path traversal"
        )
    return text


def _require_text(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text
