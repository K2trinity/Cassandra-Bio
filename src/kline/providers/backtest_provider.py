"""Backtest result provider for K-line workspaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.backtest import runner


class BacktestResultProvider:
    def __init__(self, results_dir: Path | None = None):
        self.results_dir = (
            Path(results_dir) if results_dir is not None else runner.RESULTS_DIR
        )

    def load_last_run(self, ticker: str) -> dict[str, Any] | None:
        requested_ticker = str(ticker or "").strip().upper()
        if not requested_ticker:
            return None

        index = self._load_index()
        latest_by_ticker = index.get("latest_by_ticker")
        if not isinstance(latest_by_ticker, dict):
            return None

        entry = latest_by_ticker.get(requested_ticker)
        if not isinstance(entry, dict):
            return None

        run_id = str(entry.get("run_id") or "")
        if not runner.RUN_ID_PATTERN.fullmatch(run_id):
            return None

        payload = self._load_payload(run_id)
        if not isinstance(payload, dict):
            return None

        payload_ticker = str(payload.get("ticker") or "").strip().upper()
        if payload_ticker != requested_ticker:
            return None

        return payload

    def _load_index(self) -> dict[str, Any]:
        try:
            with open(self.results_dir / "index.json", "r", encoding="utf-8") as f:
                index = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
        return index if isinstance(index, dict) else {}

    def _load_payload(self, run_id: str) -> dict[str, Any] | None:
        try:
            with open(self.results_dir / f"{run_id}.json", "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None
