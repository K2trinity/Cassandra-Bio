"""Compatibility helpers for PDF dependency diagnostics."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Tuple


def prepare_pango_environment() -> Optional[str]:
    """Best-effort PATH setup for Windows GTK/Pango runtimes.

    Returns the first newly added runtime path, or None if unchanged.
    """
    if not sys.platform.startswith("win"):
        return None

    candidates = [
        os.environ.get("GTK_BIN_PATH", ""),
        r"C:\Program Files\GTK3-Runtime Win64\bin",
        r"C:\Program Files\GTK4-Runtime Win64\bin",
        r"C:\msys64\mingw64\bin",
        r"C:\msys64\ucrt64\bin",
    ]

    current_path = os.environ.get("PATH", "")
    entries = current_path.split(os.pathsep) if current_path else []

    for raw in candidates:
        if not raw:
            continue
        path = Path(raw)
        if not path.exists():
            continue
        normalized = str(path)
        if normalized in entries:
            continue
        os.environ["PATH"] = normalized + os.pathsep + current_path
        return normalized

    return None


def check_pango_available() -> Tuple[bool, str]:
    """Return a lightweight dependency status message for PDF rendering."""
    try:
        import weasyprint  # noqa: F401

        return True, "WeasyPrint dependencies look available"
    except Exception as exc:  # pragma: no cover - environment-dependent
        return False, f"WeasyPrint/Pango dependency check failed: {exc}"


__all__ = ["prepare_pango_environment", "check_pango_available"]
