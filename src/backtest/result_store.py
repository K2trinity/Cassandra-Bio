"""Dependency-neutral helpers for persisted backtest result payloads."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

RESULTS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "backtest_results"
)
RUN_ID_PATTERN = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}$")


def load_run_payload(
    run_id: str,
    results_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Load a persisted single-run backtest payload by run_id."""
    if not RUN_ID_PATTERN.fullmatch(str(run_id or "")):
        return None

    root = Path(results_dir) if results_dir is not None else RESULTS_DIR
    path = root / f"{run_id}.json"
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    return payload if isinstance(payload, dict) else None
