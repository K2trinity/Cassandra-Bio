"""
Cassandra - Biomedical Research Workflow Platform
Flask API Backend with LangGraph Integration

This is the main entry point for the Cassandra web application.
It provides a REST API for triggering biomedical research analysis workflows
and serves the modern web interface.

Architecture:
- Flask: REST API server
- SocketIO: Real-time progress updates
- LangGraph: Multi-agent orchestration workflow
"""

import os
import sys
import json
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import markdown

# ── Force unbuffered output so VSCode integrated terminal shows logs in real time
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
try:
    # Both stdout AND stderr must be line-buffered for VSCode to show real-time
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
    sys.stderr.reconfigure(line_buffering=True, encoding="utf-8")
except AttributeError:
    pass  # Python < 3.7

from flask import Flask, render_template, request, jsonify, send_file, Response, redirect, url_for
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from loguru import logger

# Import configuration
from config import Settings

# Import the core LangGraph workflow
from src.services.workflow_service import WorkflowService
_workflow_service = WorkflowService()

# ============================================================================
# Application Configuration
# ============================================================================

# Load settings from config.py / .env
config = Settings()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY if hasattr(config, 'SECRET_KEY') else 'cassandra-biomedical-research-2026'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file upload
app.config['TEMPLATES_AUTO_RELOAD'] = True  # Disable template caching for development
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable static file caching
# Werkzeug 3.x: TRUSTED_HOSTS=None disables host header validation (dev mode)
app.config['TRUSTED_HOSTS'] = None

# Enable CORS for development
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Initialize SocketIO with CORS support
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

from src.kline.routes import kline_bp

app.register_blueprint(kline_bp)

VALID_ANALYSIS_TARGET_TYPES = {"auto", "disease", "company"}

WORKFLOW_STEPS = (
    {
        "id": "intake",
        "stage": "intake",
        "label": "Intake routing",
        "detail": "Query + target mode",
        "group": "setup",
    },
    {
        "id": "harvest",
        "stage": "collect",
        "label": "Evidence harvest",
        "detail": "ClinicalTrials + sources",
        "group": "setup",
    },
    {
        "id": "evidence_review",
        "stage": "review",
        "label": "Evidence review",
        "detail": "Normalize + filter",
        "group": "setup",
    },
    {
        "id": "extension_slots",
        "stage": "slots",
        "label": "Slot preparation",
        "detail": "Report contract payload",
        "group": "setup",
    },
    {
        "id": "evidence_synthesis",
        "stage": "analysis",
        "label": "Evidence synthesis",
        "detail": "Signals + summaries",
        "group": "parallel",
    },
    {
        "id": "clinical_analysis",
        "stage": "analysis",
        "label": "Clinical analysis",
        "detail": "Trial status + risk",
        "group": "parallel",
    },
    {
        "id": "quality_assessment",
        "stage": "analysis",
        "label": "Quality assessment",
        "detail": "Coverage + confidence",
        "group": "parallel",
    },
    {
        "id": "writing",
        "stage": "write",
        "label": "Report writing",
        "detail": "Markdown + HTML + PDF",
        "group": "final",
    },
    {
        "id": "kline_bridge",
        "stage": "validate",
        "label": "K-line bridge",
        "detail": "Company events + ticker validation",
        "group": "final",
    },
)
WORKFLOW_STEP_IDS = tuple(step["id"] for step in WORKFLOW_STEPS)
WORKFLOW_STEP_BY_ID = {step["id"]: step for step in WORKFLOW_STEPS}
WORKFLOW_NODE_PROGRESS = {
    "harvester": (
        ("harvest", "complete", 34, "Node complete: Evidence harvest."),
        ("evidence_review", "active", 36, "Reviewing and normalizing source evidence..."),
    ),
    "extension_handoff": (
        ("evidence_review", "complete", 48, "Node complete: Evidence review."),
        ("extension_slots", "complete", 58, "Node complete: Slot preparation."),
        ("evidence_synthesis", "complete", 68, "Node complete: Evidence synthesis."),
        ("clinical_analysis", "complete", 76, "Node complete: Clinical analysis."),
        ("quality_assessment", "complete", 84, "Node complete: Quality assessment."),
        ("writing", "active", 86, "Composing the final report..."),
    ),
    "writer": (
        ("writing", "complete", 94, "Node complete: Report writing."),
        ("kline_bridge", "active", 96, "Checking whether this report can seed K-line events..."),
    ),
    "report_to_kline_bridge": (
        ("kline_bridge", "complete", 98, "Node complete: K-line bridge."),
    ),
}


def _default_step_status() -> Dict[str, str]:
    return {step_id: "pending" for step_id in WORKFLOW_STEP_IDS}


# Global state for tracking active analysis
active_analysis: Dict[str, Any] = {
    "running": False,
    "status": "idle",
    "query": None,
    "analysis_target_type": "auto",
    "thread": None,
    "result": None,
    "result_payload": None,
    "error": None,
    # ── v2 additions ──
    "task_id": None,          # UUID for this task
    "progress": 0,            # 0–100 integer
    "current_step": None,     # current step name
    "step_status": _default_step_status(),
    "started_at": None,
    "completed_at": None,
}

# Event history cache — for reconnect replay
event_history: deque = deque(maxlen=1000)
event_counter: int = 0
event_history_lock = threading.Lock()

# Cancel signal — per-task Event keyed by task_id, avoids cross-task race conditions
_cancel_event = threading.Event()
_current_task_id: Optional[str] = None  # task_id of the currently running analysis

# Thread pool for parallel analysis sub-tasks
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cassandra-worker")


def _normalize_analysis_target_type(value: Any) -> str:
    target_type = str(value or "auto").strip().lower()
    if not target_type:
        target_type = "auto"
    if target_type not in VALID_ANALYSIS_TARGET_TYPES:
        raise ValueError("Invalid analysis_target_type")
    return target_type


def _reset_active_analysis():
    """Reset global analysis state to idle. Call after crash, cancel, or completion."""
    global active_analysis
    active_analysis["running"] = False
    active_analysis["status"] = "idle"
    active_analysis["thread"] = None
    active_analysis["error"] = active_analysis.get("error")  # preserve error
    active_analysis["progress"] = active_analysis.get("progress", 0)
    active_analysis["result_payload"] = None
    active_analysis["analysis_target_type"] = "auto"
    active_analysis["step_status"] = _default_step_status()


def _start_thread_watchdog(thread: threading.Thread, task_id: Optional[str] = None, timeout: int = 3600) -> None:
    """
    Background watchdog: if the analysis thread dies unexpectedly (exception,
    timeout, etc.) without setting running=False, auto-reset the flag so the
    user can start a new analysis without restarting the server.
    """
    def _watch():
        thread.join(timeout=timeout)
        current_thread = active_analysis.get("thread")
        current_task_id = active_analysis.get("task_id")
        current_status = str(active_analysis.get("status") or "").lower()

        # Ignore stale watchdogs from prior tasks.
        if task_id and current_task_id != task_id:
            return

        # If task already ended (or was reset), watchdog should stay silent.
        if (not active_analysis.get("running")) or current_status in {"idle", "complete", "cancelled", "error"}:
            return

        # Only report when this exact watched thread is still the active thread.
        if current_thread is not thread:
            return

        if current_thread is not None and not current_thread.is_alive():
            logger.warning("⚠️  Watchdog: analysis thread died unexpectedly — resetting state.")
            active_analysis["running"] = False
            active_analysis["status"] = "error"
            active_analysis["error"] = active_analysis.get("error") or "Thread terminated unexpectedly"
            try:
                _emit_event("analysis_error", {
                    "success": False,
                    "error": active_analysis["error"],
                    "step": active_analysis.get("current_step"),
                    "progress": active_analysis.get("progress", 0),
                })
            except Exception:
                pass
    t = threading.Thread(target=_watch, daemon=True, name="watchdog")
    t.start()


# ============================================================================
# Logging Configuration
# ============================================================================

# Configure loguru for beautiful console output
# IMPORTANT: use os.write() to bypass Python's buffer entirely — this is the
# only reliable way to get real-time output in VSCode's PowerShell terminal on
# Windows, because even sys.stdout.reconfigure(line_buffering=True) has no
# effect when VSCode pipes stdout (non-TTY mode).
_stdout_fd = sys.__stdout__.fileno() if hasattr(sys.__stdout__, 'fileno') else 1
def _stdout_flush_sink(message):
    """Loguru sink that writes directly to fd-1 (unbuffered).
    Bypasses Python's IO buffer so VSCode integrated terminal shows every
    line in real time regardless of buffering mode."""
    try:
        os.write(_stdout_fd, message.encode('utf-8', errors='replace'))
    except OSError:
        # Fallback to normal flush if fd is not available
        sys.stdout.write(message)
        sys.stdout.flush()

logger.remove()  # Remove default handler
logger.add(
    _stdout_flush_sink,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True,   # Force ANSI colors (VSCode terminal supports them)
    enqueue=False,   # Synchronous write — no internal queue delay
)

# Redirect Werkzeug (Flask dev server) logs to stdout as well,
# so all server output appears in the same VSCode terminal stream.
import logging as _logging
_wz_log = _logging.getLogger("werkzeug")
_wz_log.setLevel(_logging.INFO)
_wz_handler = _logging.StreamHandler(sys.stdout)
_wz_handler.setFormatter(_logging.Formatter("%(message)s"))
_wz_log.handlers = [_wz_handler]
_wz_log.propagate = False

# Add file logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
logger.add(
    log_dir / "cassandra_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    level="DEBUG"
)


# ============================================================================
# ============================================================================
# Event Emission Helpers
# ============================================================================

def _emit_event(event_type: str, payload: Dict[str, Any]) -> None:
    """
    线程安全的事件发送 + 缓存历史，支持断线重连后的事件补发。
    payload 自动注入 id 字段，前端用于断线重连后的去重与顺序控制。
    """
    global event_counter
    with event_history_lock:
        event_counter += 1
        eid = event_counter
        # 注入 id 到 payload（前端 _lastEventId 用此字段跟踪）
        enriched_payload = {**payload, "id": eid}
        event = {
            "id": eid,
            "type": event_type,
            "payload": enriched_payload,
            "timestamp": datetime.now().isoformat(),
        }
        event_history.append(event)
    socketio.emit(event_type, enriched_payload)


def _emit_progress(step: str, status: str, pct: int, message: str = "") -> None:
    """
    发送统一的进度事件（百分比 + 步骤 + 状态）。
    同时更新 active_analysis 进度字段。
    """
    active_analysis.setdefault("step_status", _default_step_status())
    step_meta = WORKFLOW_STEP_BY_ID.get(step, {})
    active_analysis["progress"] = pct
    active_analysis["current_step"] = step
    if step in active_analysis["step_status"]:
        active_analysis["step_status"][step] = status
    _emit_event("progress", {
        "step": step,
        "step_label": step_meta.get("label", step),
        "status": status,
        "percentage": pct,
        "message": message,
        "task_id": active_analysis.get("task_id"),
        "query": active_analysis.get("query"),
        "analysis_target_type": active_analysis.get("analysis_target_type", "auto"),
    })
    _emit_event("step", {
        "step": step,
        "step_label": step_meta.get("label", step),
        "status": status,
        "percentage": pct,
        "task_id": active_analysis.get("task_id"),
        "query": active_analysis.get("query"),
        "analysis_target_type": active_analysis.get("analysis_target_type", "auto"),
    })


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_empty_source_guidance(
    *,
    query: str,
    analysis_target_type: str,
    biomedical_profile: Dict[str, Any],
    clinical_data: Dict[str, Any],
    source_audit: Dict[str, Any],
    harvested_count: int,
) -> Dict[str, Any] | None:
    trial_records = _safe_int(clinical_data.get("trial_records"))
    retained_count = _safe_int(source_audit.get("retained_count"), trial_records)
    raw_count = _safe_int(source_audit.get("raw_count"), _safe_int(clinical_data.get("raw_records")))
    if harvested_count > 0 or trial_records > 0 or retained_count > 0:
        return None

    disease_areas = biomedical_profile.get("disease_areas")
    parsed_target = (
        biomedical_profile.get("target_name")
        or biomedical_profile.get("company_name")
        or (disease_areas[0] if isinstance(disease_areas, list) and disease_areas else None)
        or biomedical_profile.get("disease_name")
        or query
    )
    target_type = biomedical_profile.get("target_type") or analysis_target_type or "disease"

    if raw_count > 0:
        reason = (
            "ClinicalTrials returned source rows, but no rows matched the parsed "
            "disease condition after strict relevance filtering."
        )
        likely_issue = (
            "Likely a prompt/target mismatch or overly narrow condition match: "
            "the source had rows, but they did not match the parsed disease target."
        )
    else:
        reason = "ClinicalTrials returned zero rows for the parsed target."
        likely_issue = (
            "Most often this is a prompt/target mismatch: the Investigation route "
            "needs a named disease condition or company sponsor, not only a drug, "
            "safety topic, mechanism, or generic clinical-trials phrase."
        )

    return {
        "status": "empty_source",
        "severity": "warning",
        "source": "clinicaltrials.gov",
        "query": query,
        "target_type": target_type,
        "parsed_target": parsed_target,
        "raw_count": raw_count,
        "retained_count": retained_count,
        "rejected_count": _safe_int(
            source_audit.get("rejected_count"),
            _safe_int(clinical_data.get("rejected_records")),
        ),
        "reason": reason,
        "likely_issue": likely_issue,
        "actions": [
            "Use Disease landscape on <disease>, focusing on <drug/safety/mechanism> for disease work.",
            "Use Company pipeline for <company/sponsor> and select Company pipeline for sponsor work.",
            "Upload PDFs when the evidence is document-based or ClinicalTrials has no matching public rows.",
            "If a known disease or sponsor still returns zero, retry later and verify ClinicalTrials access.",
        ],
    }


# ============================================================================
# Custom Logger Interceptor for SocketIO Streaming
# ============================================================================

class SocketIOLogHandler:
    """
    自定义日志处理器，将运行日志实时推送到前端。
    附加功能：
    - 日志去重（避免重复消息刷屏）
    """

    def __init__(self):
        self._last_message: str = ""
        self._dedup_lock = threading.Lock()

    def write(self, message: str):
        if not message.strip() or not active_analysis["running"]:
            return
        try:
            # 简单去重：跳过与上一条完全相同的消息
            with self._dedup_lock:
                if message.strip() == self._last_message:
                    return
                self._last_message = message.strip()

            # Parse log level from message
            level = "info"

            if "ERROR" in message or "❌" in message or "CRITICAL" in message:
                level = "error"
            elif "WARNING" in message or "⚠" in message:
                level = "warning"
            elif "SUCCESS" in message or "✅" in message:
                level = "success"
            elif "Scanning" in message or "🔍" in message:
                level = "scanning"

            clean_msg = message.strip()
            _emit_event('log', {
                'level': level,
                'message': clean_msg,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.debug(f"Failed to emit log to SocketIO: {e}")

    def flush(self):
        pass


# Add SocketIO handler to loguru
socketio_handler = SocketIOLogHandler()
logger.add(socketio_handler.write, level="INFO")


# ============================================================================
# Routes: Frontend Pages
# ============================================================================

@app.route('/')
def root_redirect():
    """Default entry: open the New Investigation workspace."""
    return redirect(url_for('index'))


@app.route('/investigation')
def index():
    """Mission Control - Main Dashboard"""
    return render_template('index.html', workflow_steps=WORKFLOW_STEPS)


@app.route('/config')
def config_page():
    """System Configuration Page"""
    return render_template('config.html')


# ============================================================================
# Routes: Core API Endpoints
# ============================================================================

@app.route('/api/analyze', methods=['POST'])
def analyze():
    """
    POST /api/analyze
    
    Triggers a biomedical research analysis workflow.
    Executes the LangGraph workflow asynchronously in a background thread.
    
    Request Body:
        {
            "query": "Analyze pembrolizumab cardiotoxicity",
            "pdfs": ["path/to/file1.pdf", "path/to/file2.pdf"]  # Optional
        }
    
    Response:
        {
            "status": "accepted",
            "message": "Analysis started",
            "query": "..."
        }
    """
    global active_analysis, _current_task_id

    # --- Stale-state guard ---
    # If running=True but the thread is dead (crashed / never cleaned up),
    # auto-reset so the user isn't permanently locked out without a server restart.
    thread = active_analysis.get("thread")
    if active_analysis["running"] and (thread is None or not thread.is_alive()):
        logger.warning("⚠️  /api/analyze: running=True but thread is dead — auto-resetting state.")
        active_analysis["running"] = False
        _cancel_event.clear()

    if active_analysis["running"]:
        return jsonify({
            "status": "error",
            "message": "An analysis is already in progress. Please wait for it to complete."
        }), 409
    
    # Parse request data - handle both JSON and FormData
    if request.is_json:
        data = request.get_json(silent=True) or {}
        query = data.get('query', '').strip()
        pdf_paths = data.get('pdfs', [])
        requested_narrative_language = data.get("narrative_language")
        requested_target_type = data.get("analysis_target_type")
    else:
        # Handle FormData (multipart/form-data with file uploads)
        data = {}
        query = request.form.get('query', '').strip()
        pdf_files = request.files.getlist('files')
        requested_narrative_language = request.form.get("narrative_language")
        requested_target_type = request.form.get("analysis_target_type")
        
        # Save uploaded PDFs temporarily
        pdf_paths = []
        if pdf_files:
            upload_dir = Path("uploads")
            upload_dir.mkdir(exist_ok=True)
            
            for file in pdf_files:
                if file.filename and file.filename.endswith('.pdf'):
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_filename = f"{timestamp}_{file.filename}"
                    file_path = upload_dir / safe_filename
                    file.save(file_path)
                    pdf_paths.append(str(file_path))
                    logger.info(f"📄 Saved uploaded PDF: {file_path}")

    narrative_language = str(
        requested_narrative_language
        or getattr(config, "REPORT_NARRATIVE_LANGUAGE", "zh")
    ).strip().lower()
    if narrative_language not in {"zh", "en"}:
        narrative_language = "zh"

    try:
        analysis_target_type = _normalize_analysis_target_type(requested_target_type)
    except ValueError as exc:
        return jsonify({
            "status": "error",
            "message": str(exc),
        }), 400
    
    # Validate query
    if not query:
        return jsonify({
            "status": "error",
            "message": "Query is required"
        }), 400
    
    logger.info(f"🚀 New analysis request: {query}")
    logger.info(f"📄 PDF paths: {len(pdf_paths)} files")
    
    # Reset active analysis state
    import uuid as _uuid
    active_analysis = {
        "running": True,
        "status": "running",
        "query": query,
        "analysis_target_type": analysis_target_type,
        "thread": None,
        "result": None,
        "result_payload": None,
        "error": None,
        "task_id": str(_uuid.uuid4()),
        "progress": 0,
        "current_step": "intake",
        "step_status": _default_step_status(),
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
    }
    # Assign a task-local cancel event and clear any previous signal
    _current_task_id = active_analysis["task_id"]  # set above when building new dict
    _cancel_event.clear()
    with event_history_lock:
        event_history.clear()
    
    # Define background task
    # Capture the task_id so this thread can detect if it has been superseded
    _this_task_id = active_analysis["task_id"]

    def run_analysis_async():
        """Execute LangGraph workflow with per-node progress streaming."""
        global active_analysis

        try:
            _emit_progress("intake", "active", 3, "Preparing analysis request...")
            _emit_progress("intake", "complete", 8, "Node complete: Intake routing.")
            _emit_progress("harvest", "active", 10, "Starting evidence harvest...")
            logger.info("🔬 Starting Cassandra streaming workflow...")

            # ── Ticker thread: smoothly animates within the current node's pct range ──
            _ticker_stop = threading.Event()
            _current_range = [10, 34]  # mutable via list

            def _ticker():
                while not _ticker_stop.is_set():
                    cur = active_analysis.get("progress", 3)
                    lo, hi = _current_range
                    ceiling = hi - 1  # never reach hi; real node completion will do that
                    if cur < ceiling:
                        nxt = min(cur + 1, ceiling)
                        active_analysis["progress"] = nxt
                        socketio.emit("progress", {
                            "step": active_analysis.get("current_step", "harvest"),
                            "status": "active",
                            "percentage": nxt,
                            "message": "",
                            "task_id": active_analysis.get("task_id"),
                            "query": active_analysis.get("query"),
                            "analysis_target_type": active_analysis.get("analysis_target_type", "auto"),
                        })
                    _ticker_stop.wait(timeout=3.0)  # tick every ~3s

            ticker_thread = threading.Thread(target=_ticker, daemon=True)
            ticker_thread.start()

            # ── Stream workflow nodes ──
            result = None
            for node_name, partial_state in _workflow_service.stream(
                user_query=query,
                thread_id=_this_task_id,
                pdf_paths=pdf_paths if pdf_paths else None,
                narrative_language=narrative_language,
                analysis_target_type=analysis_target_type,
            ):
                # Check for cancellation signal from /api/reset or page refresh.
                # Guard with task_id to avoid cancelling a NEW analysis that
                # started while this thread was still winding down.
                if _cancel_event.is_set() and active_analysis.get("task_id") == _this_task_id:
                    logger.warning("⚠️  Analysis cancelled by user — stopping stream.")
                    _ticker_stop.set()
                    _emit_event('analysis_cancelled', {
                        'message': 'Analysis was cancelled.',
                        'task_id': active_analysis.get("task_id"),
                        'query': active_analysis.get("query"),
                        'analysis_target_type': active_analysis.get("analysis_target_type", "auto"),
                    })
                    active_analysis["running"] = False
                    active_analysis["status"] = "cancelled"
                    active_analysis["error"] = "Cancelled by user"
                    active_analysis["result_payload"] = None
                    return
                result = partial_state  # keep last partial as fallback
                if node_name in WORKFLOW_NODE_PROGRESS:
                    for step_id, status, pct, msg in WORKFLOW_NODE_PROGRESS[node_name]:
                        _current_range[0] = pct
                        _current_range[1] = min(99, pct + 2)  # allow ticker above node completion
                        _emit_progress(step_id, status, pct, msg)

            _ticker_stop.set()

            # ── result is the full accumulated state from stream ──
            # If streaming somehow missed the final_report, fall back to sync invoke
            if result is None or not result.get("final_report"):
                logger.warning("⚠️  Stream gave no final_report — running sync invoke as fallback...")
                _emit_progress("writing", "active", 86, "Re-running writer (stream fallback)...")
                result = _workflow_service.run(
                    user_query=query,
                    pdf_paths=pdf_paths if pdf_paths else None,
                    narrative_language=narrative_language,
                    analysis_target_type=analysis_target_type,
                )
            
            # Store result
            active_analysis["result"] = result
            active_analysis["running"] = False
            active_analysis["status"] = "complete"
            active_analysis["completed_at"] = datetime.now().isoformat()

            full_report_markdown = ""
            report_path = result.get('final_report_path')
            
            if report_path and os.path.exists(report_path):
                try:
                    with open(report_path, 'r', encoding='utf-8') as f:
                        full_report_markdown = f.read()
                    logger.success(f"✅ Loaded full report for display ({len(full_report_markdown)} chars)")
                except Exception as e:
                    logger.warning(f"Could not load report content: {e}")
                    full_report_markdown = "**Error:** Unable to load report content. Check logs for details."
            else:
                logger.warning("Report path not found or does not exist")
                full_report_markdown = "**Warning:** Report file not generated. Analysis may have failed."
            
            # ── Generate HTML report from IR/Markdown ──
            html_report_path = None
            pdf_report_path_v2 = None

            # 优先使用 IR 管线生成的 HTML/PDF（含图表和完整排版）
            _ir_html = result.get('final_report_html_path')
            _ir_pdf = result.get('final_report_pdf_path')
            if _ir_html and os.path.exists(_ir_html):
                html_report_path = _ir_html
                logger.info(f"✅ Using IR-pipeline HTML: {_ir_html}")
            if _ir_pdf and os.path.exists(_ir_pdf):
                pdf_report_path_v2 = _ir_pdf
                logger.info(f"✅ Using IR-pipeline PDF: {_ir_pdf}")

            # 降级：如果 IR 管线未生成，从 Markdown 渲染
            if not html_report_path or not pdf_report_path_v2:
                try:
                    from src.engines.report_engine.renderers import PDFRenderer, HTMLRenderer
                    title = f"Cassandra Analysis: {query[:60]}"

                    if not html_report_path:
                        html_renderer = HTMLRenderer()
                        html_content = html_renderer.render_from_markdown(
                            full_report_markdown, title=title, query=query, standalone=True
                        )
                        html_path = Path("final_reports") / f"{Path(report_path).stem}.html" if report_path else \
                            Path("final_reports") / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                        html_path.parent.mkdir(exist_ok=True)
                        html_path.write_text(html_content, encoding="utf-8")
                        html_report_path = str(html_path)
                        logger.success(f"✅ HTML report generated (fallback): {html_path.name}")

                    if not pdf_report_path_v2:
                        pdf_renderer = PDFRenderer()
                        pdf_path_v2 = Path(html_report_path).with_suffix(".pdf") if html_report_path else \
                            Path("final_reports") / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                        pdf_renderer.render_markdown_to_file(
                            full_report_markdown, pdf_path_v2, title=title, query=query
                        )
                        pdf_report_path_v2 = str(pdf_path_v2)
                        logger.success(f"✅ PDF generated (fallback): {pdf_path_v2.name}")
                except Exception as e:
                    logger.warning(f"Advanced PDF generation failed, falling back to legacy: {e}")

            # ── Emit completion ──
            biomedical_profile = result.get("biomedical_profile", {}) or {}
            analysis_focus = result.get("analysis_focus") or biomedical_profile.get("analysis_focus") or "disease-oriented"
            disease_areas = result.get("disease_areas") or biomedical_profile.get("disease_areas") or []
            clinical_data = result.get("clinical_data") or biomedical_profile.get("clinical_data") or {}
            evidence_stats = result.get("evidence_stats") or biomedical_profile.get("evidence_stats") or {}
            extension_payloads = result.get("extension_payloads") or {}
            disease_report_package = result.get("disease_report_package") or {}
            source_audit = result.get("source_audit") or disease_report_package.get("source_audit") or {}
            harvested_count = len(result.get('harvested_data', []))
            kline_bridge = result.get("kline_bridge") or {}
            empty_source_guidance = _build_empty_source_guidance(
                query=query,
                analysis_target_type=analysis_target_type,
                biomedical_profile=biomedical_profile,
                clinical_data=clinical_data,
                source_audit=source_audit,
                harvested_count=harvested_count,
            )

            _emit_progress("kline_bridge", "complete", 100, "✅ Analysis complete!")
            completion_payload = {
                'success': True,
                'task_id': active_analysis.get("task_id"),
                'query': query,
                'analysis_target_type': analysis_target_type,
                'narrative_language': narrative_language,
                'report_path': pdf_report_path_v2 or report_path,
                'html_report_path': html_report_path,
                'full_report_markdown': full_report_markdown,
                # 优先用 result 中 LLM 生成的 executive_summary，
                # 降级取报告正文前 1500 字符（去除 Markdown 标题行）
                'executive_summary': (
                    result.get('executive_summary')
                    or result.get('executive_summary_text')
                    or next(
                        (line.strip() for line in (full_report_markdown or "").splitlines()
                         if line.strip() and not line.startswith('#')),
                        full_report_markdown[:1500] if full_report_markdown else ""
                    )
                ),
                'summary': {
                    'harvested_items': harvested_count,
                    'disease_areas': len(disease_areas),
                    'trial_records': clinical_data.get('trial_records', 0),
                    'publication_records': evidence_stats.get('publication_records', 0),
                    'extension_slots': len(extension_payloads),
                },
                'analysis_focus': analysis_focus,
                'biomedical_profile': biomedical_profile,
                'disease_areas': disease_areas,
                'drug_baselines': result.get('drug_baselines') or biomedical_profile.get('drug_baselines') or [],
                'drug_class_distribution': result.get('drug_class_distribution') or biomedical_profile.get('drug_class_distribution') or [],
                'drug_catalog': result.get('drug_catalog') or biomedical_profile.get('drug_catalog') or [],
                'target_signals': result.get('target_signals') or biomedical_profile.get('target_signals') or [],
                'company_entities': result.get('company_entities') or biomedical_profile.get('company_entities') or [],
                'clinical_data': clinical_data,
                'evidence_stats': evidence_stats,
                'source_audit': source_audit,
                'empty_source_guidance': empty_source_guidance,
                'kline_bridge': kline_bridge,
                'kline_bridge_status': result.get("kline_bridge_status") or kline_bridge.get("status"),
                'kline_bridge_skip_reason': (
                    result.get("kline_bridge_skip_reason")
                    if result.get("kline_bridge_skip_reason") is not None
                    else kline_bridge.get("skip_reason")
                ),
                'kline_ticker': result.get("kline_ticker") or kline_bridge.get("ticker"),
                'kline_url': result.get("kline_url") or kline_bridge.get("kline_url"),
                'kline_event_count': result.get("kline_event_count", kline_bridge.get("event_count", 0)),
                'extension_payloads': extension_payloads,
                'contract_version': result.get('dataflow_contract_version'),
            }
            active_analysis["result_payload"] = completion_payload
            _emit_event('analysis_complete', completion_payload)
            
            logger.info("✅ Analysis complete!")
            
        except Exception as e:
            # Stop ticker if it was started
            try:
                _ticker_stop.set()
            except NameError:
                pass
            logger.error(f"❌ Analysis failed: {e}")
            import traceback
            error_trace = traceback.format_exc()
            logger.error(error_trace)
            
            active_analysis["error"] = str(e)
            active_analysis["running"] = False
            active_analysis["status"] = "error"
            active_analysis["completed_at"] = datetime.now().isoformat()
            active_analysis["result_payload"] = None
            
            _emit_progress(
                active_analysis.get("current_step", "harvest"),
                "error",
                active_analysis.get("progress", 0),
                f"❌ Analysis failed: {str(e)}"
            )
            _emit_event('analysis_error', {
                'success': False,
                'error': str(e),
                'task_id': active_analysis.get("task_id"),
                'query': active_analysis.get("query"),
                'analysis_target_type': active_analysis.get("analysis_target_type", "auto"),
                'step': active_analysis.get("current_step"),
                'progress': active_analysis.get("progress", 0),
            })
    
    # Start background thread + watchdog
    analysis_thread = threading.Thread(target=run_analysis_async, daemon=True, name="analysis")
    analysis_thread.start()
    active_analysis["thread"] = analysis_thread
    _start_thread_watchdog(analysis_thread, task_id=active_analysis.get("task_id"))
    
    return jsonify({
        "status": "accepted",
        "message": "Analysis started. Monitor progress via WebSocket.",
        "query": query,
        "analysis_target_type": analysis_target_type,
        "task_id": active_analysis.get("task_id"),
    }), 202


@app.route('/api/reset', methods=['POST'])
def reset_analysis():
    """
    POST /api/reset
    Force-reset the analysis state so a new analysis can be started.
    Use when a previous analysis crashed or the running flag is stuck.
    """
    global active_analysis
    thread = active_analysis.get("thread")
    if thread and thread.is_alive():
        # Signal the analysis thread to stop at the next iteration checkpoint
        _cancel_event.set()
        logger.warning("⚠️  Cancel signal sent to analysis thread")

    prev_query = active_analysis.get("query", "unknown")
    active_analysis["running"] = False
    active_analysis["status"] = "idle"
    active_analysis["thread"] = None
    active_analysis["error"] = None
    active_analysis["result"] = None
    active_analysis["result_payload"] = None
    active_analysis["task_id"] = None
    active_analysis["analysis_target_type"] = "auto"
    active_analysis["progress"] = 0
    active_analysis["current_step"] = None
    active_analysis["step_status"] = _default_step_status()
    with event_history_lock:
        event_history.clear()

    logger.info(f"♻️  Analysis state reset (was: '{prev_query}')")
    return jsonify({"status": "ok", "message": "Analysis state reset. You can start a new analysis."})



@app.route('/api/status', methods=['GET'])
def get_status():
    """
    GET /api/status
    返回分析工作流的完整状态（含进度百分比），供前端轮询降级模式使用。
    """
    # Auto-reset if the thread died but running flag is still True
    thread = active_analysis.get("thread")
    if active_analysis.get("running") and thread and not thread.is_alive():
        logger.warning("⚠️  Status poll detected dead thread — auto-resetting state")
        active_analysis["running"] = False

    return jsonify({
        "running": active_analysis["running"],
        "status": active_analysis.get("status"),
        "query": active_analysis["query"],
        "analysis_target_type": active_analysis.get("analysis_target_type", "auto"),
        "error": active_analysis["error"],
        "task_id": active_analysis.get("task_id"),
        "progress": active_analysis.get("progress", 0),
        "current_step": active_analysis.get("current_step"),
        "step_status": active_analysis.get("step_status", {}),
        "started_at": active_analysis.get("started_at"),
        "completed_at": active_analysis.get("completed_at"),
        "result_payload": active_analysis.get("result_payload"),
    })


@app.route('/api/heartbeat', methods=['GET'])
def heartbeat():
    """GET /api/heartbeat — 服务器健康检查 + 心跳（前端每15秒调用一次）"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "analysis_running": active_analysis["running"],
    })


@app.route('/api/events/history', methods=['GET'])
def get_event_history():
    """
    GET /api/events/history?since=<event_id>
    
    返回指定 event_id 之后的所有历史事件，用于断线重连后的事件补发。
    """
    since = int(request.args.get("since", 0))
    with event_history_lock:
        missed = [e for e in event_history if e["id"] > since]
    return jsonify({
        "events": missed,
        "total": len(missed),
        "latest_id": missed[-1]["id"] if missed else since,
    })


@app.route('/api/reports/latest', methods=['GET'])
def get_latest_report():
    """
    GET /api/reports/latest?format=pdf|markdown
    
    Downloads the most recently generated report.
    Scans final_reports/ directory for PDF or Markdown files.
    
    Query Parameters:
        format (str): 'pdf' or 'markdown' (default: 'pdf')
    
    Response:
        Binary file download (PDF or Markdown)
    """
    try:
        from flask import send_file
        
        reports_dir = Path("final_reports")
        
        if not reports_dir.exists():
            return jsonify({
                "success": False,
                "message": "Reports directory not found"
            }), 404
        
        # Determine requested format
        requested_format = request.args.get('format', 'pdf').lower()
        file_extension = '.pdf' if requested_format == 'pdf' else '.md'
        
        # Find all matching files，过滤掉乱码 PDF（旧 reportlab 回退生成）
        all_pdf_files = list(reports_dir.glob(f"*{file_extension}"))
        if file_extension == '.pdf':
            report_files = [p for p in all_pdf_files if not _is_pdf_garbled(p)]
            if len(report_files) < len(all_pdf_files):
                logger.warning(f"⚠️ Skipped {len(all_pdf_files)-len(report_files)} garbled PDF(s)")
        else:
            report_files = all_pdf_files

        if not report_files:
            # Fallback: try alternative format
            fallback_ext = '.md' if file_extension == '.pdf' else '.pdf'
            report_files = list(reports_dir.glob(f"*{fallback_ext}"))
            
            if not report_files:
                return jsonify({
                    "success": False,
                    "message": f"No {requested_format} reports found. Run an analysis first."
                }), 404
            
            logger.warning(f"Requested {requested_format} not found, serving {fallback_ext[1:]} instead")
            file_extension = fallback_ext
        
        # Sort by modification time (most recent first)
        latest_report = max(report_files, key=lambda p: p.stat().st_mtime)
        
        # Determine MIME type
        mime_type = 'application/pdf' if file_extension == '.pdf' else 'text/markdown'
        
        logger.info(f"📥 Serving report: {latest_report.name} ({mime_type})")
        
        # Send file for download
        return send_file(
            latest_report,
            mimetype=mime_type,
            as_attachment=True,
            download_name=latest_report.name
        )
        
    except Exception as e:
        logger.error(f"Failed to serve report: {e}")
        return jsonify({
            "success": False,
            "message": f"Error retrieving report: {str(e)}"
        }), 500


@app.route('/api/reports/list', methods=['GET'])
def list_reports():
    """
    GET /api/reports/list
    
    Lists all reports in the final_reports directory.
    
    Response:
        {
            "success": true,
            "reports": [
                {
                    "filename": "report_20260209_123456.md",
                    "title": "Analysis Report",
                    "timestamp": "2026-02-09T12:34:56",
                    "size": 12345,
                    "preview": "Executive summary..."
                }
            ]
        }
    """
    try:
        reports_dir = Path("final_reports")
        
        if not reports_dir.exists():
            return jsonify({
                "success": True,
                "reports": []
            })
        
        # Collect HTML reports first (primary format), then md/json as fallback
        # For each stem, prefer .html > .pdf > .md > .json
        all_files = (
            list(reports_dir.glob("*.html")) +
            list(reports_dir.glob("*.pdf")) +
            list(reports_dir.glob("*.md")) +
            list(reports_dir.glob("*.json"))
        )

        # De-duplicate by stem: keep the highest-priority format per stem
        _priority = {".html": 0, ".pdf": 1, ".md": 2, ".json": 3}
        stem_map: dict = {}
        for p in all_files:
            stem = p.stem
            if stem not in stem_map or _priority.get(p.suffix, 9) < _priority.get(stem_map[stem].suffix, 9):
                stem_map[stem] = p
        report_files = list(stem_map.values())

        # Sort by modification time (newest first)
        report_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        
        reports = []
        for report_path in report_files:
            stat = report_path.stat()
            
            # Extract title: from <title> tag for HTML, else from filename
            title = report_path.stem.replace('_', ' ').title()
            if report_path.suffix == '.html':
                try:
                    import re as _re
                    with open(report_path, 'r', encoding='utf-8', errors='ignore') as f:
                        head = f.read(2048)
                    m = _re.search(r'<title[^>]*>([^<]+)</title>', head, _re.IGNORECASE)
                    if m:
                        title = m.group(1).strip()
                except Exception:
                    pass
            
            # Preview: not needed for HTML/PDF; extract from md/json
            preview = ""
            if report_path.suffix in ('.md', '.json'):
                try:
                    with open(report_path, 'r', encoding='utf-8') as f:
                        content = f.read(500)
                    lines = content.split('\n')
                    for line in lines:
                        if line.strip() and not line.startswith('#'):
                            preview = line.strip()[:200]
                            break
                except Exception:
                    pass

            # Check whether a PDF version already exists
            pdf_exists = (reports_dir / (report_path.stem + '.pdf')).exists()
            
            reports.append({
                "filename": report_path.name,
                "title": title,
                "timestamp": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "size": stat.st_size,
                "preview": preview,
                "has_pdf": pdf_exists or report_path.suffix == '.pdf',
                "source_type": report_path.suffix.lstrip('.'),
            })
        
        return jsonify({
            "success": True,
            "reports": reports
        })
        
    except Exception as e:
        logger.error(f"Failed to list reports: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@app.route('/api/reports/view/<filename>', methods=['GET'])
def view_report(filename: str):
    """
    GET /api/reports/view/<filename>
    
    Views a specific report file in browser (not as download).
    """
    try:
        report_path = Path("final_reports") / filename
        
        if not report_path.exists():
            return jsonify({
                "success": False,
                "message": "Report not found"
            }), 404
        
        # Read report content
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        import html as _html_mod
        # Serve HTML reports directly, render Markdown inline, fallback to <pre>
        if filename.endswith('.html'):
            # Directly serve the generated HTML report (Chart.js / MathJax inside)
            from flask import Response as _Response
            return _Response(content, mimetype='text/html; charset=utf-8')
        elif filename.endswith('.md'):
            return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{filename}</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .prose {{ max-width: 900px; margin: 0 auto; }}
        .prose h1 {{ font-size: 2rem; font-weight: bold; margin: 1.5rem 0 1rem; }}
        .prose h2 {{ font-size: 1.5rem; font-weight: bold; margin: 1.25rem 0 .75rem; border-bottom: 2px solid #e2e8f0; padding-bottom: .5rem; }}
        .prose h3 {{ font-size: 1.25rem; font-weight: 600; margin: 1rem 0 .5rem; }}
        .prose p {{ margin-bottom: 1rem; line-height: 1.6; }}
        .prose ul, .prose ol {{ margin-left: 1.5rem; margin-bottom: 1rem; }}
        .prose li {{ margin-bottom: .5rem; }}
        .prose code {{ background: #f7fafc; padding: .2rem .4rem; border-radius: .25rem; font-family: monospace; }}
        .prose pre {{ background: #2d3748; color: #e2e8f0; padding: 1rem; border-radius: .5rem; overflow-x: auto; }}
        .prose table {{ width: 100%; border-collapse: collapse; margin-bottom: 1rem; }}
        .prose th {{ background: #edf2f7; padding: .75rem; text-align: left; font-weight: bold; border: 1px solid #cbd5e0; }}
        .prose td {{ padding: .75rem; border: 1px solid #e2e8f0; }}
    </style>
</head>
<body class="bg-gray-50 p-8">
    <div class="prose"><div id="content"></div></div>
    <script>document.getElementById('content').innerHTML = marked.parse({json.dumps(content)});</script>
</body>
</html>"""
        else:
            # JSON / plain text fallback
            return f"<pre style='white-space:pre-wrap;word-break:break-all;padding:1rem;'>{_html_mod.escape(content)}</pre>"
        
    except Exception as e:
        logger.error(f"Failed to view report: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@app.route('/api/reports/download/<filename>', methods=['GET'])
def download_report(filename: str):
    """
    GET /api/reports/download/<filename>

    Always delivers a PDF for download:
    - If a same-stem .pdf already exists, serve it directly.
    - If the source is .html, convert via WeasyPrint → PDF.
    - If the source is .md, convert via existing convert_markdown_to_pdf.
    - Otherwise serve the file as-is.
    """
    try:
        report_path = Path("final_reports") / filename

        if not report_path.exists():
            return jsonify({"success": False, "message": "Report not found"}), 404

        stem = Path(filename).stem
        pdf_candidate = Path("final_reports") / (stem + ".pdf")

        # ── Case 1: pre-existing PDF sibling ──
        if pdf_candidate.exists() and report_path.suffix != '.pdf':
            if _is_pdf_garbled(pdf_candidate):
                logger.warning(f"⚠️ Garbled PDF detected, deleting for regeneration: {pdf_candidate.name}")
                pdf_candidate.unlink(missing_ok=True)
            else:
                logger.info(f"📥 Serving pre-built PDF: {pdf_candidate.name}")
                return send_file(
                    pdf_candidate,
                    as_attachment=True,
                    download_name=stem + ".pdf",
                    mimetype='application/pdf'
                )

        # ── Case 2: source is already PDF ──
        if report_path.suffix == '.pdf':
            return send_file(
                report_path,
                as_attachment=True,
                download_name=filename,
                mimetype='application/pdf'
            )

        # ── Case 3: HTML → PDF ──
        if report_path.suffix == '.html':
            try:
                pdf_path = convert_html_to_pdf(report_path)
                return send_file(
                    pdf_path,
                    as_attachment=True,
                    download_name=stem + ".pdf",
                    mimetype='application/pdf'
                )
            except Exception as e:
                logger.error(f"HTML→PDF conversion failed: {e}")
                # Fall back: serve HTML directly
                return send_file(
                    report_path,
                    as_attachment=True,
                    download_name=filename,
                    mimetype='text/html'
                )

        # ── Case 4: Markdown → PDF ──
        if report_path.suffix == '.md':
            try:
                pdf_path = convert_markdown_to_pdf(report_path)
                return send_file(
                    pdf_path,
                    as_attachment=True,
                    download_name=stem + ".pdf",
                    mimetype='application/pdf'
                )
            except Exception as e:
                logger.error(f"MD→PDF conversion failed, falling back to markdown: {e}")
                return send_file(
                    report_path,
                    as_attachment=True,
                    download_name=filename,
                    mimetype='text/markdown'
                )

        # ── Fallback: serve as-is ──
        return send_file(report_path, as_attachment=True, download_name=filename)

    except Exception as e:
        logger.error(f"Failed to download report: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/reports/pdf/<filename>', methods=['GET'])
def view_report_pdf(filename: str):
    """
    GET /api/reports/pdf/<filename>

    Returns a PDF inline (not as attachment) so the browser / iframe can
    render it directly.  Converts HTML / Markdown if no PDF exists yet.
    """
    try:
        stem = Path(filename).stem
        reports_dir = Path("final_reports")
        pdf_candidate = reports_dir / (stem + ".pdf")

        # If we already have a PDF, serve it inline immediately
        if pdf_candidate.exists():
            logger.info(f"📄 Inline PDF: {pdf_candidate.name}")
            return send_file(
                pdf_candidate,
                mimetype='application/pdf',
                as_attachment=False,
                download_name=pdf_candidate.name
            )

        # Try to find a source file to convert
        for ext in ('.html', '.md'):
            src = reports_dir / (stem + ext)
            if src.exists():
                try:
                    if ext == '.html':
                        pdf_path = convert_html_to_pdf(src)
                    else:
                        pdf_path = convert_markdown_to_pdf(src)
                    return send_file(
                        pdf_path,
                        mimetype='application/pdf',
                        as_attachment=False,
                        download_name=pdf_path.name
                    )
                except Exception as e:
                    logger.error(f"Conversion to PDF failed for inline view ({src.name}): {e}")
                    # Fall back: serve HTML/MD as inline HTML so the iframe still shows something
                    if ext == '.html':
                        content = src.read_text(encoding='utf-8')
                        from flask import Response as _R
                        return _R(content, mimetype='text/html; charset=utf-8')

        # Last resort: look for the exact filename
        direct = reports_dir / filename
        if direct.exists():
            return send_file(direct, mimetype='application/pdf', as_attachment=False)

        return jsonify({"success": False, "message": "PDF not found and conversion failed"}), 404

    except Exception as e:
        logger.error(f"Failed to serve inline PDF: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================================
# Helper Functions: PDF Generation (v2 — WeasyPrint / pdfkit / PyMuPDF / reportlab)
# ============================================================================

def _is_pdf_garbled(pdf_path: Path) -> bool:
    """
    快速检测 PDF 是否包含 JS/CSS 乱码内容。
    若首页文字中出现典型 JavaScript 标志，则认为是就是旧 reportlab 回退生成的乱码 PDF。
    """
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        if not doc.page_count:
            return True
        text = doc[0].get_text()[:800]
        doc.close()
        garbled_markers = ["MathJax", ":root {", "function(", "var chartData",
                           "--primary:", "box-sizing", "@keyframes", ".report-"]
        return any(m in text for m in garbled_markers)
    except Exception:
        return False


def convert_html_to_pdf(html_path: Path) -> Path:
    """
    将 HTML 文件转换为 PDF（WeasyPrint → pdfkit → PyMuPDF 降级）。
    若当前 PDF 已存在且检测为乱码，则重新生成。
    Returns the Path to the generated PDF (same stem, .pdf suffix).
    """
    pdf_path = html_path.with_suffix(".pdf")
    # 如果已有 PDF 并且没有乱码，直接复用
    if pdf_path.exists() and not _is_pdf_garbled(pdf_path):
        return pdf_path

    html_content = html_path.read_text(encoding="utf-8")

    # ── WeasyPrint ──
    try:
        from weasyprint import HTML as WP_HTML
        WP_HTML(string=html_content, base_url=str(html_path.parent)).write_pdf(str(pdf_path))
        logger.info(f"✅ HTML→PDF via WeasyPrint: {pdf_path.name}")
        return pdf_path
    except Exception as e:
        logger.warning(f"WeasyPrint failed for HTML ({e}), trying pdfkit…")

    # ── pdfkit (wkhtmltopdf) ──
    try:
        import pdfkit
        options = {
            'encoding': 'UTF-8',
            'no-outline': None,
            'quiet': '',
            'enable-local-file-access': '',
        }
        pdfkit.from_string(html_content, str(pdf_path), options=options)
        logger.info(f"✅ HTML→PDF via pdfkit: {pdf_path.name}")
        return pdf_path
    except Exception as e:
        logger.warning(f"pdfkit also failed: {e}, trying PyMuPDF…")

    # ── PyMuPDF (fitz.Story) ──
    try:
        import re as _re
        import fitz
        clean = _re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html_content, flags=_re.IGNORECASE)
        clean = _re.sub(r'<style[^>]*>[\s\S]*?</style>', '', clean, flags=_re.IGNORECASE)
        clean = _re.sub(r'<link[^>]+>', '', clean, flags=_re.IGNORECASE)
        clean = _re.sub(r'@import\s+url\([^)]+\);?', '', clean)
        user_css = (
            "body { font-family: serif; font-size: 11pt; line-height: 1.6; }"
            "h1,h2,h3,h4 { font-weight: bold; margin-top: 1em; }"
            "table { border-collapse: collapse; width: 100%; }"
            "th, td { border: 1px solid #ccc; padding: 4px 8px; }"
        )
        story = fitz.Story(html=clean, user_css=user_css)
        import io as _io
        buf = _io.BytesIO()
        writer = fitz.DocumentWriter(buf, "pdf")
        mediabox = fitz.paper_rect("a4")
        more = 1
        while more:
            device = writer.begin_page(mediabox)
            more, _ = story.place(mediabox)
            story.draw(device)
            writer.end_page()
        writer.close()
        pdf_path.write_bytes(buf.getvalue())
        logger.info(f"✅ HTML→PDF via PyMuPDF: {pdf_path.name}")
        return pdf_path
    except Exception as e:
        logger.error(f"PyMuPDF also failed: {e}")
        raise RuntimeError(f"All HTML→PDF converters failed: {e}")


def convert_markdown_to_pdf(markdown_path: Path) -> Path:
    """
    将 Markdown 文件转换为专业 PDF（WeasyPrint 优先，逐级降级）。
    """
    try:
        from src.engines.report_engine.renderers import PDFRenderer
        renderer = PDFRenderer()
        content = markdown_path.read_text(encoding="utf-8")
        title = markdown_path.stem.replace("_", " ").title()
        pdf_path = markdown_path.with_suffix(".pdf")
        renderer.render_markdown_to_file(content, pdf_path, title=title)
        logger.info(f"✅ PDF generated (v2): {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.warning(f"v2 PDF renderer failed ({e}), using legacy reportlab fallback")
        return _legacy_reportlab_convert(markdown_path)


def _legacy_reportlab_convert(markdown_path: Path) -> Path:
    """原有 reportlab 降级实现（改进版：支持 Unicode 字体）"""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        with open(markdown_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        html_content = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])

        # ── 注册系统 Unicode TrueType 字体 ──
        _FONT_CANDS = [
            (r"C:\Windows\Fonts\calibri.ttf",   "Calibri"),
            (r"C:\Windows\Fonts\arial.ttf",      "Arial"),
            (r"C:\Windows\Fonts\verdana.ttf",    "Verdana"),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  "DejaVuSans"),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "LiberationSans"),
        ]
        _body_font = "Helvetica"  # 内置兜底
        for _fp, _fn in _FONT_CANDS:
            import os as _os
            if _os.path.isfile(_fp):
                try:
                    pdfmetrics.registerFont(TTFont(_fn, _fp))
                    _body_font = _fn
                    break
                except Exception:
                    pass

        # ── Unicode → ASCII 安全替换 ──
        _UNICODE_MAP = {
            "\u2014": "--", "\u2013": "-", "\u2018": "'", "\u2019": "'",
            "\u201c": '"',  "\u201d": '"', "\u2022": "*", "\u2026": "...",
            "\u00b0": " deg", "\u00b1": "+/-", "\u00d7": "x", "\u2264": "<=",
            "\u2265": ">=", "\u2260": "!=", "\u03b1": "alpha", "\u03b2": "beta",
            "\u03b3": "gamma", "\u03bc": "mu", "\u00ae": "(R)", "\u00a9": "(C)",
            "\u2122": "(TM)", "\u00a0": " ", "\u200b": "", "\ufeff": "",
        }

        def _safe_text(t: str) -> str:
            for ch, rp in _UNICODE_MAP.items():
                t = t.replace(ch, rp)
            t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            # 最终兜底：强制编码到 latin-1
            try:
                t.encode("latin-1")
            except UnicodeEncodeError:
                t = t.encode("latin-1", errors="replace").decode("latin-1")
            return t

        pdf_path = markdown_path.with_suffix('.pdf')
        doc = SimpleDocTemplate(str(pdf_path), pagesize=letter,
                                topMargin=0.75 * inch, bottomMargin=0.75 * inch)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle', parent=styles['Heading1'],
            fontName=_body_font, fontSize=18, spaceAfter=12,
        )
        body_style = ParagraphStyle(
            'UniBody', parent=styles['Normal'],
            fontName=_body_font, fontSize=10, leading=14,
        )

        import re as _re
        text_content = _re.sub('<[^<]+?>', ' ', html_content)
        story = []
        for line in text_content.split('\n'):
            if line.strip():
                is_heading = line.strip().startswith('#')
                style = title_style if is_heading else body_style
                safe_line = _safe_text(line.replace('#', '').strip()[:2000])
                try:
                    story.append(Paragraph(safe_line, style))
                    story.append(Spacer(1, 0.1 * inch))
                except Exception:
                    ascii_line = line.replace('#', '').strip()[:2000].encode('ascii', errors='replace').decode('ascii')
                    story.append(Paragraph(ascii_line, style))
                    story.append(Spacer(1, 0.1 * inch))
        doc.build(story)
        logger.info(f"✅ PDF generated (legacy): {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.error(f"Legacy PDF conversion also failed: {e}")
        raise


# ============================================================================
# Routes: Configuration API
# ============================================================================

@app.route('/api/test-gemini', methods=['POST'])
def test_gemini():
    """
    POST /api/test-gemini
    
    Tests Google Gemini API connection via Vertex AI.
    
    Request Body:
        {"project": "gen-lang-client-...", "location": "global"}
        (Optional — defaults to env vars GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION)
    
    Response:
        {"success": true, "message": "Connection successful"}
    """
    try:
        data = request.json or {}
        project = data.get('project') or os.getenv('GOOGLE_CLOUD_PROJECT')
        location = data.get('location') or os.getenv('GOOGLE_CLOUD_LOCATION', 'global')
        
        if not project:
            return jsonify({
                "success": False,
                "error": "Google Cloud project ID required. Set GOOGLE_CLOUD_PROJECT env var or pass 'project' in request body."
            }), 400
        
        # Test Vertex AI connection using unified google-genai SDK
        from google import genai
        client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )
        
        # Use the configured report model or the latest verified Vertex global fallback.
        model_name = getattr(config, 'REPORT_MODEL_NAME', 'gemini-3.1-pro-preview')
        response = client.models.generate_content(
            model=model_name,
            contents="Hello, test connection",
        )
        
        return jsonify({
            "success": True,
            "message": "Vertex AI Gemini connection successful",
            "project": project,
            "location": location,
            "model": model_name,
            "test_response": response.text[:100] if response.text else "(empty)"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500



@app.route('/api/test-redis', methods=['POST'])
def test_redis():
    """
    POST /api/test-redis
    
    Tests Redis connection.
    
    Request Body:
        {"uri": "redis://localhost:6379/0"}
    
    Response:
        {"success": true, "message": "Connection successful"}
    """
    try:
        data = request.json
        
        import redis
        
        r = redis.from_url(data.get('uri'))
        r.ping()
        
        return jsonify({
            "success": True,
            "message": "Redis connection successful"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/save-config', methods=['POST'])
def save_config():
    """
    POST /api/save-config
    
    Saves system configuration to .env file.
    
    Request Body:
        {
            "gemini": {...},
            "redis": {...},
            "engines": {...}
        }
    
    Response:
        {"success": true, "message": "Configuration saved"}
    """
    try:
        config_data = request.json
        
        # TODO: Implement actual .env file writing
        # For now, just acknowledge receipt
        logger.info(f"Configuration update requested: {list(config_data.keys())}")
        
        return jsonify({
            "success": True,
            "message": "Configuration saved (mock - implement .env writing)"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/get-config', methods=['GET'])
def get_system_config():
    """
    GET /api/get-config
    
    Returns current system configuration.
    
    Response:
        {
            "gemini": {...},
            "redis": {...}
        }
    """
    try:
        return jsonify({
            "gemini": {
                "model": getattr(config, 'REPORT_MODEL_NAME', 'gemini-3.1-pro-preview'),
                "temperature": getattr(config, 'REPORT_TEMPERATURE', 1.0),
                "max_tokens": getattr(config, 'REPORT_MAX_TOKENS', 8192)
            },
            "redis": {
                "uri": getattr(config, 'REDIS_URL', 'redis://localhost:6379/0')
            },
            "max_results": 50
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================================
# SocketIO Events
# ============================================================================

@socketio.on('connect')
def handle_connect():
    """Client connected to SocketIO — replay missed events if client provides last_event_id"""
    logger.info(f"🔌 Client connected: {request.sid}")

    # 先做死线程检测，确保向前端发送的快照是准确的
    if active_analysis["running"]:
        _t = active_analysis.get("thread")
        if _t is None or not _t.is_alive():
            logger.warning("⚠️  handle_connect: running=True but thread is dead — auto-resetting.")
            active_analysis["running"] = False
            _cancel_event.clear()

    # 发送连接确认 + 当前状态快照（此时 running 已是准确值）
    emit('connected', {
        'message': 'Connected to Cassandra backend',
        'analysis_running': active_analysis["running"],
        'analysis_status': active_analysis.get("status"),
        'task_id': active_analysis.get("task_id"),
        'query': active_analysis.get("query"),
        'analysis_target_type': active_analysis.get("analysis_target_type", "auto"),
        'progress': active_analysis.get("progress", 0),
        'current_step': active_analysis.get("current_step"),
        'step_status': active_analysis.get("step_status", {}),
    })

    # 如果分析确实在运行（线程存活），推送当前进度
    if active_analysis["running"]:
        emit('progress', {
            'step': active_analysis.get("current_step", "harvest"),
            'status': 'active',
            'percentage': active_analysis.get("progress", 0),
            'message': 'Analysis in progress...',
            'task_id': active_analysis.get("task_id"),
            'query': active_analysis.get("query"),
            'analysis_target_type': active_analysis.get("analysis_target_type", "auto"),
        })


@socketio.on('disconnect')
def handle_disconnect():
    """Client disconnected from SocketIO"""
    logger.info(f"🔌 Client disconnected: {request.sid}")


@socketio.on('heartbeat')
def handle_heartbeat(data):
    """前端心跳包响应 — 15秒发送一次"""
    emit('heartbeat_ack', {
        'timestamp': datetime.now().isoformat(),
        'status': 'ok',
        'analysis_running': active_analysis["running"],
        'analysis_status': active_analysis.get("status"),
    })


@socketio.on('request_replay')
def handle_replay(data):
    """
    客户端断线重连后请求补发历史事件。
    data: {"since": <last_event_id>}
    """
    since = int(data.get("since", 0))
    with event_history_lock:
        missed = [e for e in event_history if e["id"] > since]
    logger.info(f"📡 Replaying {len(missed)} missed events to {request.sid} (since={since})")
    for event in missed:
        # payload 已含 id 字段（_emit_event 注入），直接转发即可
        emit(event["type"], event["payload"])


@socketio.on("anomaly_signal")
def handle_anomaly_signal(data):
    """Forward link: K-line anomaly → trigger Cassandra report."""
    logger.info(f"📊 Anomaly signal received: {data}")
    ticker = data.get("ticker", "")
    date = data.get("date", "")
    signal_type = data.get("type", "")
    magnitude = data.get("magnitude", 0)

    user_query = (
        f"Analyze the {signal_type.replace('_', ' ')} anomaly for {ticker} "
        f"on {date} (magnitude: {magnitude:.1f}). "
        f"Identify the catalyst and assess impact on the investment thesis."
    )

    socketio.emit("anomaly_acknowledged", {
        "ticker": ticker,
        "date": date,
        "status": "report_queued",
        "query": user_query,
    })


@socketio.on("request_report")
def handle_request_report(data):
    """Compatibility bridge: legacy K-line clients forward to the main analysis flow."""
    logger.info(f"📊 Report requested for event: {data}")
    event_type = data.get("event_type", "")
    ticker = data.get("ticker", "")
    catalyst = data.get("catalyst", "")
    date = data.get("date", "")

    user_query = (
        f"Generate a detailed analysis of the {event_type.replace('_', ' ')} "
        f"event for {ticker} on {date}: {catalyst}"
    )
    with app.test_request_context(
        "/api/analyze",
        method="POST",
        json={"query": user_query, "pdfs": []},
    ):
        response = app.make_response(analyze())
        response_payload = response.get_json(silent=True) or {}

    if response.status_code == 202:
        socketio.emit("report_queued", {
            "ticker": ticker,
            "event_id": data.get("event_id"),
            "status": "queued",
            "task_id": response_payload.get("task_id"),
            "query": user_query,
        })
        return

    _emit_event("analysis_error", {
        "success": False,
        "task_id": response_payload.get("task_id") or active_analysis.get("task_id"),
        "query": user_query,
        "error": response_payload.get("message") or response_payload.get("error") or "Failed to queue report analysis.",
        "step": active_analysis.get("current_step"),
        "progress": active_analysis.get("progress", 0),
    })


# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == '__main__':
    logger.info("="*80)
    logger.info("🧬 Cassandra - Biomedical Research Workflow Platform")
    logger.info("="*80)
    logger.info(f"🌐 Server: http://0.0.0.0:{config.PORT}")
    logger.info(f"🔬 LangGraph Workflow: ✅ Loaded")
    logger.info("="*80)
    
    # Create required directories
    Path("final_reports").mkdir(exist_ok=True)
    Path("uploads").mkdir(exist_ok=True)
    
    # Start Flask-SocketIO server
    socketio.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=False,
        allow_unsafe_werkzeug=True
    )
