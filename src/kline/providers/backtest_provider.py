"""Backtest result provider for K-line workspaces."""

from __future__ import annotations

from typing import Any


class BacktestResultProvider:
    def __init__(self, load_run: object | None = None):
        # Phase 1 has no stable last-run index; keep compatibility without wiring persistence.
        del load_run

    def load_last_run(self, ticker: str) -> dict[str, Any] | None:
        return None
