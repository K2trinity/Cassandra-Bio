"""
Cassandra - Unified Knowledge Graph Query Logger

Centralizes knowledge_query.log write logic across different modules (Flask API, GraphRAG nodes, etc.)
to avoid scattered implementations and ensure consistent logging.
"""

import json
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger

# Log file paths
ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT_DIR / "logs"
KNOWLEDGE_LOG_FILE = LOG_DIR / "knowledge_query.log"

_log_lock = threading.Lock()


def _sanitize_log_text(text: str) -> str:
    """Remove newlines/carriage returns to prevent log pollution."""
    return str(text).replace("\n", " ").replace("\r", " ").strip()


def _trim_text(text: str, limit: int = 300) -> str:
    """Truncate long text to avoid excessive log size."""
    text = _sanitize_log_text(text)
    return text if len(text) <= limit else text[:limit] + "..."


def compact_records(items):
    """
    Compress nodes/records into compact log format to avoid log pollution by large fields.
    """
    compacted = []
    if not items:
        return compacted

    for item in items:
        if not isinstance(item, dict):
            compacted.append(_trim_text(str(item)))
            continue

        entry = {}
        for key, value in item.items():
            if isinstance(value, (str, int, float, bool)):
                entry[key] = _trim_text(str(value))
            else:
                try:
                    entry[key] = _trim_text(json.dumps(value, ensure_ascii=False))
                except Exception:
                    entry[key] = _trim_text(str(value))
        compacted.append(entry)
    return compacted


def init_knowledge_log(force_reset: bool = True):
    """
    Initialize knowledge graph query log file.

    Args:
        force_reset: True to reset file and write initialization marker; False to write only if file doesn't exist.
    """
    try:
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        mode = "w" if force_reset or not KNOWLEDGE_LOG_FILE.exists() else "a"
        with _log_lock, open(KNOWLEDGE_LOG_FILE, mode, encoding="utf-8") as f:
            f.write(f"=== Knowledge Query Log Initialized - {start_time} ===\n")
        logger.info("Knowledge Query: knowledge_query.log initialized")
    except Exception as exc:  # pragma: no cover - runtime execution only
        logger.exception(f"Knowledge Query: Failed to initialize log: {exc}")


def _ensure_log_file():
    """Ensure log file is created and writable, without overwriting existing content."""
    if not KNOWLEDGE_LOG_FILE.exists():
        init_knowledge_log(force_reset=False)


def append_knowledge_log(source: str, payload: dict):
    """Record knowledge graph query keywords and complete request data."""
    try:
        _ensure_log_file()
        timestamp = datetime.now().strftime("%H:%M:%S")
        clean_source = _sanitize_log_text(source or "UNKNOWN")
        serialized = json.dumps(payload, ensure_ascii=False)
        sanitized = _sanitize_log_text(serialized)
        with _log_lock, open(KNOWLEDGE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [KNOWLEDGE] [{clean_source}] {sanitized}\n")
    except Exception as exc:  # pragma: no cover - log failure doesn't affect main workflow
        logger.warning(f"Knowledge Query: Failed to write log: {exc}")
