"""Shared logger resolver for harvest engine package."""

from __future__ import annotations

import importlib
import logging


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:  # pragma: no cover - optional dependency fallback
        return logging.getLogger("src.engines.harvest")


logger = _resolve_logger()
