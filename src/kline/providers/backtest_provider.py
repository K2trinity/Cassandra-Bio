"""Backtest result provider for K-line workspaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class BacktestResultProvider:
    def __init__(self, load_run: Callable[[str], dict[str, Any] | None] | None = None):
        if load_run is None:
            from src.backtest.runner import load_saved_run

            load_run = load_saved_run
        self.load_run = load_run

    def load_last_run(self, ticker: str) -> dict[str, Any] | None:
        return None
