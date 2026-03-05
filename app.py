"""
Cassandra - Biomedical Due Diligence Platform
Flask API Backend with LangGraph Integration

This is the main entry point for the Cassandra web application.
It provides a REST API for triggering biomedical due diligence investigations
and serves the modern web interface.

Architecture:
- Flask: REST API server
- SocketIO: Real-time progress updates
- LangGraph: Multi-agent orchestration workflow
- Neo4j: Knowledge graph storage (optional)
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
from typing import Dict, Any, Optional, List
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

from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from loguru import logger

# Import configuration
from config import Settings

# Import the core LangGraph workflow
from src.agents.supervisor import run_bio_short_seller, stream_bio_short_seller
from src.graph.state import AgentState

# Conditionally import Neo4j GraphManager
try:
    from src.graph.manager import GraphManager
    NEO4J_AVAILABLE = True
except ImportError as e:
    logger.warning(f"GraphManager import failed: {e}. Knowledge graph features will use mock data.")
    NEO4J_AVAILABLE = False


# ============================================================================
# Application Configuration
# ============================================================================

# Load settings from config.py / .env
config = Settings()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY if hasattr(config, 'SECRET_KEY') else 'cassandra-biomedical-due-diligence-2026'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file upload
app.config['TEMPLATES_AUTO_RELOAD'] = True  # Disable template caching for development
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable static file caching
# Werkzeug 3.x: TRUSTED_HOSTS=None disables host header validation (dev mode)
app.config['TRUSTED_HOSTS'] = None

# Enable CORS for development
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Initialize SocketIO with CORS support
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global state for tracking active analysis
active_analysis: Dict[str, Any] = {
    "running": False,
    "query": None,
    "thread": None,
    "result": None,
    "error": None,
    # ── v2 additions ──
    "task_id": None,          # UUID for this task
    "progress": 0,            # 0–100 integer
    "current_step": None,     # current step name
    "step_status": {          # per-step status
        "harvest": "pending",
        "mining": "pending",
        "auditing": "pending",
        "writing": "pending",
    },
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


def _reset_active_analysis():
    """Reset global analysis state to idle. Call after crash, cancel, or completion."""
    global active_analysis
    active_analysis["running"] = False
    active_analysis["thread"] = None
    active_analysis["error"] = active_analysis.get("error")  # preserve error
    active_analysis["progress"] = active_analysis.get("progress", 0)


def _start_thread_watchdog(thread: threading.Thread, timeout: int = 3600) -> None:
    """
    Background watchdog: if the analysis thread dies unexpectedly (exception,
    timeout, etc.) without setting running=False, auto-reset the flag so the
    user can start a new analysis without restarting the server.
    """
    def _watch():
        thread.join(timeout=timeout)
        if active_analysis.get("running") and not active_analysis.get("thread", thread).is_alive():
            logger.warning("⚠️  Watchdog: analysis thread died unexpectedly — resetting state.")
            active_analysis["running"] = False
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
    active_analysis["progress"] = pct
    active_analysis["current_step"] = step
    if step in active_analysis["step_status"]:
        active_analysis["step_status"][step] = status
    _emit_event("progress", {
        "step": step,
        "status": status,
        "percentage": pct,
        "message": message,
    })
    _emit_event("step", {"step": step, "status": status, "percentage": pct})


# ============================================================================
# Custom Logger Interceptor for SocketIO Streaming
# ============================================================================

class SocketIOLogHandler:
    """
    自定义日志处理器，将运行日志实时推送到前端。
    附加功能：
    - 图片路径提取（用于法证扫描实时预览）
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
            image_path = None

            if "ERROR" in message or "❌" in message or "CRITICAL" in message:
                level = "error"
            elif "WARNING" in message or "⚠" in message:
                level = "warning"
            elif "SUCCESS" in message or "✅" in message:
                level = "success"
            elif "Scanning" in message or "Analyzing figure" in message or "🔍" in message:
                level = "scanning"
                import re as _re
                img_match = _re.search(r'(figure_\d+|page_\d+_img_\d+)\.png', message)
                if img_match:
                    image_path = f'/static/temp/{img_match.group(0)}'

            clean_msg = message.strip()
            _emit_event('log', {
                'level': level,
                'message': clean_msg,
                'image_path': image_path,
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
def index():
    """Mission Control - Main Dashboard"""
    return render_template('index.html')


@app.route('/graph')
def graph_view():
    """Knowledge Graph Visualization Page"""
    return render_template('graph_view.html')


@app.route('/graph-debug')
def graph_debug():
    """Graph Debugging and Testing Page"""
    return render_template('graph_debug.html')


@app.route('/test-socketio')
def test_socketio():
    """SocketIO Testing Page"""
    return render_template('socketio_test.html')


@app.route('/config')
def config_page():
    """System Configuration Page"""
    return render_template('config.html')


@app.route('/static/temp/<path:filename>')
def serve_temp_image(filename: str):
    """Serve temporary forensic images for real-time preview"""
    try:
        # Try multiple possible locations
        possible_paths = [
            Path("downloads") / "temp" / filename,
            Path("downloads") / filename,
            Path("temp") / filename,
            Path("final_reports") / filename
        ]
        
        for img_path in possible_paths:
            if img_path.exists():
                return send_file(img_path, mimetype='image/png')
        
        logger.warning(f"Image not found: {filename}")
        return jsonify({"error": "Image not found"}), 404
        
    except Exception as e:
        logger.error(f"Failed to serve image {filename}: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Routes: Core API Endpoints
# ============================================================================

@app.route('/api/analyze', methods=['POST'])
def analyze():
    """
    POST /api/analyze
    
    Triggers a biomedical due diligence investigation.
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
        data = request.get_json()
        query = data.get('query', '').strip()
        pdf_paths = data.get('pdfs', [])
    else:
        # Handle FormData (multipart/form-data with file uploads)
        query = request.form.get('query', '').strip()
        pdf_files = request.files.getlist('files')
        
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
        "query": query,
        "thread": None,
        "result": None,
        "error": None,
        "task_id": str(_uuid.uuid4()),
        "progress": 0,
        "current_step": "harvest",
        "step_status": {
            "harvest": "pending",
            "mining": "pending",
            "auditing": "pending",
            "writing": "pending",
        },
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
    }
    # Assign a task-local cancel event and clear any previous signal
    _current_task_id = active_analysis["task_id"]  # set above when building new dict
    _cancel_event.clear()
    with event_history_lock:
        event_history.clear()
    
    # ── Node → (step_id, pct_start, pct_end, label) mapping ──
    _NODE_PROGRESS = {
        "harvester":    ("harvest",  3,  28, "🌾 BioHarvest: collecting PubMed / trials..."),
        "miner":        ("mining",  30,  55, "⛏️  EvidenceMiner: extracting text evidence..."),
        "auditor":      ("auditing",30,  55, "🔬 ForensicAuditor: scanning figures..."),
        "graph_builder":("auditing",58,  70, "🕸️  GraphBuilder: validating knowledge graph..."),
        "writer":       ("writing", 72,  94, "✍️  ReportWriter: composing final report..."),
    }

    # Define background task
    # Capture the task_id so this thread can detect if it has been superseded
    _this_task_id = active_analysis["task_id"]

    def run_analysis_async():
        """Execute LangGraph workflow with per-node progress streaming."""
        global active_analysis

        try:
            _emit_progress("harvest", "active", 3, "🌾 Starting BioHarvest data collection...")
            logger.info("🔬 Starting Bio-Short-Seller streaming workflow...")

            # ── Ticker thread: smoothly animates within the current node's pct range ──
            _ticker_stop = threading.Event()
            _current_range = [3, 28]  # mutable via list

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
                        })
                    _ticker_stop.wait(timeout=3.0)  # tick every ~3s

            ticker_thread = threading.Thread(target=_ticker, daemon=True)
            ticker_thread.start()

            # ── Stream workflow nodes ──
            result = None
            for node_name, partial_state in stream_bio_short_seller(
                user_query=query,
                pdf_paths=pdf_paths if pdf_paths else None
            ):
                # Check for cancellation signal from /api/reset or page refresh.
                # Guard with task_id to avoid cancelling a NEW analysis that
                # started while this thread was still winding down.
                if _cancel_event.is_set() and active_analysis.get("task_id") == _this_task_id:
                    logger.warning("⚠️  Analysis cancelled by user — stopping stream.")
                    _ticker_stop.set()
                    _emit_event('analysis_cancelled', {'message': 'Analysis was cancelled.'})
                    active_analysis["running"] = False
                    active_analysis["error"] = "Cancelled by user"
                    return
                result = partial_state  # keep last partial as fallback
                if node_name in _NODE_PROGRESS:
                    step_id, pct_lo, pct_hi, msg = _NODE_PROGRESS[node_name]
                    _current_range[0] = pct_hi
                    _current_range[1] = pct_hi + 2  # allow ticker above node completion
                    _emit_progress(step_id, "complete", pct_hi, msg)
                    # Mark the *next* step active immediately so badge flips
                    _steps_order = ["harvest", "mining", "auditing", "writing"]
                    try:
                        nxt_idx = _steps_order.index(step_id) + 1
                        if nxt_idx < len(_steps_order):
                            _emit_progress(_steps_order[nxt_idx], "active",
                                           pct_hi + 1, "")
                    except ValueError:
                        pass

            _ticker_stop.set()

            # ── result is the full accumulated state from stream ──
            # If streaming somehow missed the final_report, fall back to sync invoke
            if result is None or not result.get("final_report"):
                logger.warning("⚠️  Stream gave no final_report — running sync invoke as fallback...")
                _emit_progress("writing", "active", 72, "✍️  Re-running writer (stream fallback)...")
                result = run_bio_short_seller(
                    user_query=query,
                    pdf_paths=pdf_paths if pdf_paths else None
                )
            
            # Store result
            active_analysis["result"] = result
            active_analysis["running"] = False
            active_analysis["completed_at"] = datetime.now().isoformat()

            # ── Persist analysis to Neo4j knowledge graph (non-blocking) ──
            # Run in a daemon thread so Neo4j connection lag NEVER delays
            # SocketIO `analysis_complete` event reaching the browser.
            def _neo4j_write(result=result, query=query):
                import re as _re

                # ── 1. Resolve drug name ──
                _drug = (result.get("project_name") or "").strip()
                if not _drug:
                    _m = _re.search(
                        r'(?:analyze|assess|evaluate|investigate|audit)\s+([A-Za-z0-9\-]+)',
                        query, _re.IGNORECASE)
                    _drug = _m.group(1).title() if _m else query.split()[0].title()
                _task_id = active_analysis.get("task_id", datetime.now().strftime("%Y%m%d_%H%M%S"))
                _created = active_analysis.get("completed_at", datetime.now().isoformat())

                # ── 2. Build graph data structures (nodes + links) ──
                # Used for both Neo4j write AND local JSON cache
                _risk_nodes: List[Dict]   = []  # {name, source, target, severity}
                _rich_entities: List[Dict] = []  # {label, name, rel?, props?}
                _source_nodes: List[str]   = []  # source IDs

                # ── 2a. Extract from text_evidence (rich multi-field extraction) ──
                for _ev in result.get("text_evidence", [])[:100]:
                    if not isinstance(_ev, dict):
                        continue

                    # Risk / finding (primary node)
                    _risk = (_ev.get("risk_type") or _ev.get("finding") or
                             _ev.get("signal") or _ev.get("title") or "")[:120]
                    _src  = (_ev.get("source") or _ev.get("pmid") or _ev.get("file") or "")[:80]
                    _tgt  = (_ev.get("target") or "")[:80]
                    _mech = (_ev.get("mechanism") or "")[:80]
                    _sev  = _ev.get("severity", "")

                    if _risk:
                        _risk_nodes.append({"name": _risk, "source": _src,
                                            "target": _tgt, "severity": _sev})

                    # Target / molecular target
                    if _tgt:
                        _rich_entities.append({"label": "Target", "name": _tgt})
                    # Mechanism
                    if _mech:
                        _rich_entities.append({"label": "Mechanism", "name": _mech})
                    # AdverseEvent (separate from generic Risk)
                    _ae = _ev.get("adverse_event") or _ev.get("ae") or ""
                    if _ae:
                        _rich_entities.append({"label": "AdverseEvent", "name": str(_ae)[:120]})
                    # Disease / indication
                    _dis = _ev.get("disease") or _ev.get("indication") or _ev.get("condition") or ""
                    if _dis:
                        _rich_entities.append({"label": "Disease", "name": str(_dis)[:120]})
                    # Clinical endpoint
                    _ep = _ev.get("endpoint") or _ev.get("primary_endpoint") or ""
                    if _ep:
                        _rich_entities.append({"label": "Endpoint", "name": str(_ep)[:120]})
                    # Gene / biomarker
                    _gene = _ev.get("gene") or _ev.get("biomarker") or _ev.get("protein") or ""
                    if _gene:
                        _rich_entities.append({"label": "Gene", "name": str(_gene)[:80]})
                    # Pathway
                    _pw = _ev.get("pathway") or ""
                    if _pw:
                        _rich_entities.append({"label": "Pathway", "name": str(_pw)[:120]})
                    # Source ID
                    if _src:
                        _source_nodes.append(_src)

                # ── 2b. Extract from harvested_data (Source + Keyword nodes) ──
                for _h in result.get("harvested_data", [])[:60]:
                    if not isinstance(_h, dict):
                        continue
                    _pid   = _h.get("pmid") or _h.get("nct_id") or _h.get("id") or ""
                    _title = (_h.get("title") or "")[:120]
                    if _pid:
                        _source_nodes.append(str(_pid)[:80])
                        if _title:
                            _risk_nodes.append({"name": _title, "source": str(_pid)[:80],
                                                "target": "", "severity": ""})
                    # Keywords from abstract headings (simple heuristic)
                    _kws = _h.get("keywords") or _h.get("mesh_terms") or []
                    if isinstance(_kws, list):
                        for _kw in _kws[:5]:
                            if _kw and isinstance(_kw, str) and len(_kw) > 2:
                                _rich_entities.append({"label": "Keyword", "name": _kw[:80]})
                    # Phase / status as endpoint-like node
                    _phase = _h.get("phase") or _h.get("status") or ""
                    if _phase and isinstance(_phase, str) and len(_phase) > 2:
                        _rich_entities.append({"label": "Endpoint",
                                               "name": f"Phase: {_phase}"[:60]})

                # ── 2c. Extract query-level keywords as Keyword nodes ──
                _stopwords = {"the", "a", "an", "of", "in", "for", "and", "or",
                              "to", "is", "are", "be", "with", "analyze", "assess",
                              "evaluate", "investigate", "audit", "conduct", "strict"}
                for _qw in _re.findall(r'[A-Za-z][A-Za-z0-9\-]+', query):
                    if len(_qw) > 3 and _qw.lower() not in _stopwords:
                        _rich_entities.append({"label": "Keyword", "name": _qw})

                # De-duplicate rich entities list
                _seen_ents: set = set()
                _unique_rich: List[Dict] = []
                for _e in _rich_entities:
                    _key = (_e["label"], _e["name"].lower())
                    if _key not in _seen_ents:
                        _seen_ents.add(_key)
                        _unique_rich.append(_e)

                # ── 3. Build local JSON cache (always saved, Neo4j independent) ──
                try:
                    _cache_dir = Path("cache") / "task_graphs"
                    _cache_dir.mkdir(parents=True, exist_ok=True)
                    # Build a flat graph representation for the cache
                    _cache_nodes: List[Dict] = []
                    _cache_links: List[Dict] = []
                    _nid_map: Dict[str, str] = {}  # name:label → node_id

                    def _get_or_add_node(name: str, label: str) -> str:
                        _k = f"{label}:{name}"
                        if _k not in _nid_map:
                            _nid = f"{label.lower()}_{len(_nid_map)}"
                            _nid_map[_k] = _nid
                            _cache_nodes.append({"id": _nid, "label": label, "name": name})
                        return _nid_map[_k]

                    _analysis_nid = _get_or_add_node(_task_id[:30], "Analysis")
                    _cache_nodes[-1]["query"] = query[:200]
                    _drug_nid = _get_or_add_node(_drug, "Drug")
                    _cache_links.append({"source": _analysis_nid,
                                         "target": _drug_nid, "type": "ANALYZED"})

                    for _rn in _risk_nodes[:80]:
                        _r_nid = _get_or_add_node(_rn["name"], "Risk")
                        _cache_links.append({"source": _drug_nid,
                                              "target": _r_nid, "type": "HAS_RISK"})
                        if _rn.get("source"):
                            _s_nid = _get_or_add_node(_rn["source"], "Source")
                            _cache_links.append({"source": _s_nid,
                                                  "target": _drug_nid, "type": "REPORTS_FAILURE"})
                        if _rn.get("target"):
                            _t_nid = _get_or_add_node(_rn["target"], "Target")
                            _cache_links.append({"source": _drug_nid,
                                                  "target": _t_nid, "type": "TARGETS"})

                    for _re2 in _unique_rich[:120]:
                        _e_nid = _get_or_add_node(_re2["name"], _re2["label"])
                        _rel_type = {"Disease": "TREATS", "Mechanism": "HAS_MECHANISM",
                                     "AdverseEvent": "CAUSES_AE", "Endpoint": "HAS_ENDPOINT",
                                     "Gene": "TARGETS_GENE", "Pathway": "AFFECTS_PATHWAY",
                                     "Keyword": "ASSOCIATED_WITH",
                                     "Target": "TARGETS"}.get(_re2["label"], "ASSOCIATED_WITH")
                        _cache_links.append({"source": _drug_nid,
                                              "target": _e_nid, "type": _rel_type})

                    _cache_obj = {
                        "task_id":    _task_id,
                        "query":      query,
                        "drug_name":  _drug,
                        "created_at": _created,
                        "nodes":      _cache_nodes,
                        "links":      _cache_links,
                    }
                    _cache_path = _cache_dir / f"{_task_id}.json"
                    with open(_cache_path, "w", encoding="utf-8") as _cf:
                        json.dump(_cache_obj, _cf, ensure_ascii=False, indent=2)
                    logger.info(f"💾 Task graph cached locally: {_cache_path.name} "
                                f"({len(_cache_nodes)} nodes, {len(_cache_links)} links)")
                except Exception as _ce:
                    logger.warning(f"Local graph cache write failed: {_ce}")

                # ── 4. Write to Neo4j (optional, skipped if unavailable) ──
                try:
                    if NEO4J_AVAILABLE:
                        _graph = GraphManager()
                        if _graph.driver:
                            _graph.add_analysis_task(_task_id, query, _drug, _created)
                            _graph.link_drug_to_task(_task_id, _drug)

                            _written = 0
                            for _rn in _risk_nodes[:80]:
                                if _rn["name"]:
                                    _graph.add_risk_signal_with_task(
                                        _task_id, _drug, _rn["name"],
                                        source=_rn["source"], target=_rn["target"],
                                        metadata={"severity": _rn["severity"]}
                                    )
                                    _written += 1

                            _ent_written = _graph.add_rich_entities(
                                _task_id, _drug, _unique_rich[:120])

                            logger.success(
                                f"📊 Neo4j: task [{_task_id}] | drug={_drug} | "
                                f"{_written} risk signals + {_ent_written} entities written"
                            )
                            _graph.close()
                except Exception as _ge:
                    logger.warning(f"Neo4j write skipped (will use local cache): {_ge}")

            threading.Thread(target=_neo4j_write, daemon=True, name="neo4j-writer").start()


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
            try:
                from src.report_engine.renderers import PDFRenderer, HTMLRenderer
                title = f"Cassandra Analysis: {query[:60]}"
                
                # Generate HTML
                html_renderer = HTMLRenderer()
                html_content = html_renderer.render_from_markdown(
                    full_report_markdown, title=title, query=query, standalone=True
                )
                html_path = Path("final_reports") / f"{Path(report_path).stem}.html" if report_path else \
                    Path("final_reports") / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                html_path.parent.mkdir(exist_ok=True)
                html_path.write_text(html_content, encoding="utf-8")
                html_report_path = str(html_path)
                logger.success(f"✅ HTML report generated: {html_path.name}")
                
                # Generate PDF via WeasyPrint/pdfkit
                pdf_renderer = PDFRenderer()
                pdf_path_v2 = html_path.with_suffix(".pdf")
                pdf_renderer.render_markdown_to_file(
                    full_report_markdown, pdf_path_v2, title=title, query=query
                )
                pdf_report_path_v2 = str(pdf_path_v2)
                logger.success(f"✅ Professional PDF generated: {pdf_path_v2.name}")
            except Exception as e:
                logger.warning(f"Advanced PDF generation failed, falling back to legacy: {e}")

            # ── Emit completion ──
            _emit_progress("writing", "complete", 100, "✅ Analysis complete!")
            _emit_event('analysis_complete', {
                'success': True,
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
                    'harvested_items': len(result.get('harvested_data', [])),
                    'text_evidence': len(result.get('text_evidence', [])),
                    'forensic_evidence': len(result.get('forensic_evidence', []))
                }
            })
            
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
            active_analysis["completed_at"] = datetime.now().isoformat()
            
            _emit_progress(
                active_analysis.get("current_step", "harvest"),
                "error",
                active_analysis.get("progress", 0),
                f"❌ Analysis failed: {str(e)}"
            )
            _emit_event('analysis_error', {
                'success': False,
                'error': str(e),
                'step': active_analysis.get("current_step"),
                'progress': active_analysis.get("progress", 0),
            })
    
    # Start background thread + watchdog
    analysis_thread = threading.Thread(target=run_analysis_async, daemon=True, name="analysis")
    analysis_thread.start()
    active_analysis["thread"] = analysis_thread
    _start_thread_watchdog(analysis_thread)
    
    return jsonify({
        "status": "accepted",
        "message": "Analysis started. Monitor progress via WebSocket.",
        "query": query
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
    active_analysis["thread"] = None
    active_analysis["error"] = None
    active_analysis["progress"] = 0
    active_analysis["current_step"] = None
    active_analysis["step_status"] = {
        "harvest": "pending", "mining": "pending",
        "auditing": "pending", "writing": "pending"
    }
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
        "query": active_analysis["query"],
        "error": active_analysis["error"],
        "task_id": active_analysis.get("task_id"),
        "progress": active_analysis.get("progress", 0),
        "current_step": active_analysis.get("current_step"),
        "step_status": active_analysis.get("step_status", {}),
        "started_at": active_analysis.get("started_at"),
        "completed_at": active_analysis.get("completed_at"),
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
        
        # Find all matching files
        report_files = list(reports_dir.glob(f"*{file_extension}"))
        
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
# Helper Functions: PDF Generation (v2 — WeasyPrint / pdfkit / reportlab)
# ============================================================================

def convert_html_to_pdf(html_path: Path) -> Path:
    """
    将 HTML 文件转换为 PDF（WeasyPrint 优先，pdfkit 降级）。
    Returns the Path to the generated PDF (same stem, .pdf suffix).
    """
    pdf_path = html_path.with_suffix(".pdf")
    if pdf_path.exists():
        return pdf_path  # already generated, reuse

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
        logger.error(f"pdfkit also failed: {e}")
        raise RuntimeError(f"All HTML→PDF converters failed: {e}")


def convert_markdown_to_pdf(markdown_path: Path) -> Path:
    """
    将 Markdown 文件转换为专业 PDF（WeasyPrint 优先，逐级降级）。
    """
    try:
        from src.report_engine.renderers import PDFRenderer
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
# Routes: Knowledge Graph API
# ============================================================================

@app.route('/api/graph/data', methods=['GET'])
def get_graph_data():
    """
    GET /api/graph/data
    
    Fetches knowledge graph data from Neo4j for visualization.
    Falls back to mock data if Neo4j is unavailable.
    
    Response:
        {
            "success": true,
            "nodes": [
                {"id": "Drug_X", "label": "Drug", "name": "Pembrolizumab"},
                {"id": "AE_1", "label": "AdverseEvent", "name": "Cardiotoxicity"}
            ],
            "links": [
                {"source": "Drug_X", "target": "AE_1", "type": "CAUSES"}
            ]
        }
    """
    try:
        if NEO4J_AVAILABLE:
            # Attempt to connect to Neo4j
            graph_manager = GraphManager()
            
            # Execute Cypher query
            query = """
            MATCH (n)-[r]->(m)
            RETURN n, r, m
            LIMIT 100
            """
            
            results = graph_manager.query(query)
            
            # Format data for frontend
            nodes = []
            links = []
            node_ids = set()
            
            for record in results:
                # Extract nodes
                source = record['n']
                target = record['m']
                relationship = record['r']
                
                # Add source node
                source_id = str(source.id)
                if source_id not in node_ids:
                    nodes.append({
                        'id': source_id,
                        'label': list(source.labels)[0] if source.labels else 'Unknown',
                        'name': source.get('name', source_id),
                        'properties': dict(source)
                    })
                    node_ids.add(source_id)
                
                # Add target node
                target_id = str(target.id)
                if target_id not in node_ids:
                    nodes.append({
                        'id': target_id,
                        'label': list(target.labels)[0] if target.labels else 'Unknown',
                        'name': target.get('name', target_id),
                        'properties': dict(target)
                    })
                    node_ids.add(target_id)
                
                # Add relationship
                links.append({
                    'source': source_id,
                    'target': target_id,
                    'type': relationship.type,
                    'properties': dict(relationship)
                })
            
            return jsonify({
                "success": True,
                "source": "neo4j",
                "nodes": nodes,
                "links": links
            })
        
        else:
            # Return mock data for demo purposes
            return _get_mock_graph_data()
            
    except Exception as e:
        logger.warning(f"Failed to fetch Neo4j data: {e}. Returning mock data.")
        return _get_mock_graph_data()


def _get_mock_graph_data() -> Dict[str, Any]:
    """Returns static mock graph data for frontend testing"""
    mock_data = {
        "success": True,
        "source": "mock",
        "nodes": [
            {"id": "drug_1", "label": "Drug", "name": "Pembrolizumab"},
            {"id": "drug_2", "label": "Drug", "name": "Nivolumab"},
            {"id": "target_1", "label": "Target", "name": "PD-1 Receptor"},
            {"id": "ae_1", "label": "AdverseEvent", "name": "Cardiotoxicity"},
            {"id": "ae_2", "label": "AdverseEvent", "name": "Hepatotoxicity"},
            {"id": "trial_1", "label": "ClinicalTrial", "name": "NCT02345678"},
            {"id": "paper_1", "label": "Paper", "name": "PMID:34567890"}
        ],
        "links": [
            {"source": "drug_1", "target": "target_1", "type": "TARGETS"},
            {"source": "drug_2", "target": "target_1", "type": "TARGETS"},
            {"source": "drug_1", "target": "ae_1", "type": "CAUSES"},
            {"source": "drug_1", "target": "ae_2", "type": "CAUSES"},
            {"source": "trial_1", "target": "drug_1", "type": "STUDIES"},
            {"source": "paper_1", "target": "ae_1", "type": "REPORTS"}
        ]
    }
    
    return jsonify(mock_data)


@app.route('/test-simple', methods=['GET'])
def test_simple():
    """Simple test endpoint to verify Flask is working"""
    return jsonify({
        "status": "ok",
        "message": "Flask is working!",
        "neo4j_available": NEO4J_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    })


@app.route('/api/graph/global', methods=['GET'])
def get_global_graph():
    """GET /api/graph/global — 全局知识图谱（真实 Neo4j 数据，降级到 Mock）"""
    try:
        if NEO4J_AVAILABLE:
            gm = GraphManager()
            if gm.driver:
                data = gm.get_global_graph_data(limit=300)
                gm.close()
                if data["nodes"]:
                    return jsonify({
                        "success": True,
                        "source": "neo4j",
                        "totalNodes": len(data["nodes"]),
                        "totalRelationships": len(data["links"]),
                        "nodes": data["nodes"],
                        "links": data["links"]
                    })
        logger.info("📊 Neo4j empty/unavailable — returning mock global graph")
        return jsonify(_get_mock_global_graph())
    except Exception as e:
        logger.error(f"Failed to fetch global graph: {e}")
        return jsonify(_get_mock_global_graph())


@app.route('/api/graph/tasks', methods=['GET'])
def get_graph_tasks():
    """GET /api/graph/tasks — 列出所有已分析任务（Neo4j 优先，降级到本地 JSON 缓存）"""
    try:
        tasks = []
        source = "empty"

        # ── 优先从 Neo4j 读取 ──
        if NEO4J_AVAILABLE:
            try:
                gm = GraphManager()
                if gm.driver:
                    tasks = gm.get_all_tasks()
                    gm.close()
                    if tasks:
                        source = "neo4j"
            except Exception as _ne:
                logger.warning(f"Neo4j task list failed, falling back to cache: {_ne}")

        # ── 降级：从本地 JSON 缓存读取 ──
        if not tasks:
            _cache_dir = Path("cache") / "task_graphs"
            if _cache_dir.exists():
                _files = sorted(_cache_dir.glob("*.json"),
                                key=lambda p: p.stat().st_mtime, reverse=True)
                for _fp in _files[:100]:
                    try:
                        with open(_fp, "r", encoding="utf-8") as _cf:
                            _c = json.load(_cf)
                        tasks.append({
                            "task_id":    _c.get("task_id", _fp.stem),
                            "query":      _c.get("query", ""),
                            "drug_name":  _c.get("drug_name", ""),
                            "created_at": _c.get("created_at", ""),
                            "drug_count": sum(1 for n in _c.get("nodes", [])
                                             if n.get("label") == "Drug"),
                            "risk_count": sum(1 for n in _c.get("nodes", [])
                                             if n.get("label") == "Risk"),
                            "node_count": len(_c.get("nodes", [])),
                        })
                    except Exception:
                        pass
                if tasks:
                    source = "cache"

        return jsonify({"success": True, "source": source, "tasks": tasks})
    except Exception as e:
        logger.error(f"Failed to get tasks: {e}")
        return jsonify({"success": False, "tasks": [], "error": str(e)})


@app.route('/api/graph/task/<task_id>', methods=['GET'])
def get_task_graph_api(task_id: str):
    """GET /api/graph/task/<task_id> — 获取特定分析任务的子图谱（Neo4j 优先，降级本地缓存）"""
    try:
        # ── 优先从 Neo4j 读取 ──
        if NEO4J_AVAILABLE:
            try:
                gm = GraphManager()
                if gm.driver:
                    data = gm.get_task_graph(task_id)
                    gm.close()
                    if data["nodes"]:
                        return jsonify({"success": True, "source": "neo4j",
                                        "task_id": task_id,
                                        "nodes": data["nodes"], "links": data["links"]})
            except Exception as _ne:
                logger.warning(f"Neo4j task graph failed, falling back to cache: {_ne}")

        # ── 降级：从本地 JSON 缓存读取 ──
        _cache_path = Path("cache") / "task_graphs" / f"{task_id}.json"
        if _cache_path.exists():
            try:
                with open(_cache_path, "r", encoding="utf-8") as _cf:
                    _c = json.load(_cf)
                return jsonify({
                    "success": True,
                    "source":  "cache",
                    "task_id": task_id,
                    "query":   _c.get("query", ""),
                    "nodes":   _c.get("nodes", []),
                    "links":   _c.get("links", []),
                })
            except Exception as _ce:
                logger.error(f"Cache read failed for task {task_id}: {_ce}")

        return jsonify({"success": False, "nodes": [], "links": [],
                        "error": "Task not found in Neo4j or local cache"})
    except Exception as e:
        logger.error(f"Failed to get task graph {task_id}: {e}")
        return jsonify({"success": False, "nodes": [], "links": [], "error": str(e)})



@app.route('/api/graph/drug/<drug_name>', methods=['GET'])
def get_drug_graph(drug_name: str):
    """
    GET /api/graph/drug/<drug_name>
    
    ⭐️ 方案 B：药物专项图谱（Drill Down）
    只返回与特定药物相关的子图，包括：
    - 该药物的临床试验
    - 相关论文和作者
    - 不良事件报告
    - 监管机构警告
    - 可疑的引用链
    
    当用户在Demo中输入 "Simufilam" 并开始分析时，图谱动态刷新为这个视图。
    
    Response:
        {
            "success": true,
            "drug": "Simufilam",
            "nodes": [...],
            "links": [...]
        }
    """
    try:
        # 🔥 直接返回Mock数据，因为GraphManager.query()方法不存在
        logger.info(f"📊 Returning mock drug graph for: {drug_name}")
        return jsonify(_get_mock_drug_graph(drug_name))
            
    except Exception as e:
        logger.error(f"Failed to fetch drug graph for {drug_name}: {e}")
        return jsonify(_get_mock_drug_graph(drug_name))


@app.route('/api/graph/cross-query', methods=['GET'])
def get_cross_query():
    """
    GET /api/graph/cross-query

    跨任务关联查询 — 利用 Neo4j 图数据库跨越所有历史分析任务做关联分析。

    Query params:
        type  : shared_targets | shared_risks | drug_compare | top_entities | summary
        drug1 : 药物名（drug_compare 用）
        drug2 : 药物名（drug_compare 用）
        label : 节点类型（top_entities 用，默认 Keyword）
        min_drugs : 最少共享药物数（shared_* 用，默认 2）
        limit : 最大返回条数（默认 20）

    Examples:
        /api/graph/cross-query?type=shared_targets
        /api/graph/cross-query?type=shared_risks&min_drugs=2
        /api/graph/cross-query?type=drug_compare&drug1=Nivolumab&drug2=Pembrolizumab
        /api/graph/cross-query?type=top_entities&label=AdverseEvent&limit=15
        /api/graph/cross-query?type=summary
    """
    qtype     = request.args.get('type', 'summary')
    drug1     = request.args.get('drug1', '')
    drug2     = request.args.get('drug2', '')
    label     = request.args.get('label', 'Keyword')
    min_drugs = int(request.args.get('min_drugs', 2))
    limit     = int(request.args.get('limit', 20))

    try:
        if not NEO4J_AVAILABLE:
            return jsonify({"success": False, "error": "Neo4j driver not installed",
                            "hint": "pip install neo4j"}), 503

        gm = GraphManager()
        if not gm.driver:
            return jsonify({"success": False,
                            "error": "Neo4j unavailable — is the container running?",
                            "hint": "docker-compose up neo4j"}), 503

        if qtype == 'shared_targets':
            data = gm.get_shared_targets(min_drugs=min_drugs, limit=limit)
            gm.close()
            return jsonify({"success": True, "type": qtype,
                            "min_drugs": min_drugs, "results": data,
                            "count": len(data)})

        elif qtype == 'shared_risks':
            data = gm.get_shared_risks(min_drugs=min_drugs, limit=limit)
            gm.close()
            return jsonify({"success": True, "type": qtype,
                            "min_drugs": min_drugs, "results": data,
                            "count": len(data)})

        elif qtype == 'drug_compare':
            if not drug1 or not drug2:
                gm.close()
                return jsonify({"success": False,
                                "error": "drug_compare requires drug1 and drug2 params"}), 400
            data = gm.get_drug_comparison(drug1, drug2, limit=limit)
            gm.close()
            return jsonify({"success": True, "type": qtype,
                            "drug1": drug1, "drug2": drug2,
                            "results": data, "count": len(data)})

        elif qtype == 'top_entities':
            data = gm.get_top_entities(label=label, limit=limit)
            gm.close()
            return jsonify({"success": True, "type": qtype,
                            "label": label, "results": data,
                            "count": len(data)})

        elif qtype == 'summary':
            data = gm.get_cross_task_summary()
            gm.close()
            return jsonify({"success": True, "type": qtype, **data})

        else:
            gm.close()
            return jsonify({"success": False,
                            "error": f"Unknown type '{qtype}'",
                            "valid_types": ["shared_targets", "shared_risks",
                                            "drug_compare", "top_entities", "summary"]}), 400

    except Exception as e:
        logger.error(f"Cross-query failed [{qtype}]: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def _get_mock_global_graph() -> Dict[str, Any]:
    """返回模拟的全局欺诈网络数据（返回字典，不是jsonify）"""
    mock_data = {
        "success": True,
        "source": "mock",
        "totalNodes": 50,
        "totalRelationships": 87,
        "displayedNodes": 20,
        "nodes": [
            # 药物节点
            {"id": "drug_1", "label": "Drug", "name": "Simufilam", "group": "Drug", "properties": {"company": "Cassava Sciences"}},
            {"id": "drug_2", "label": "Drug", "name": "Pembrolizumab", "group": "Drug", "properties": {"company": "Merck"}},
            {"id": "drug_3", "label": "Drug", "name": "Nivolumab", "group": "Drug", "properties": {"company": "BMS"}},
            
            # 作者节点（可疑的共享作者）
            {"id": "author_1", "label": "Author", "name": "Dr. Hoau-Yan Wang", "group": "Author", "properties": {"suspicious": True}},
            {"id": "author_2", "label": "Author", "name": "Dr. Lindsay Burns", "group": "Author", "properties": {"suspicious": True}},
            
            # 论文节点
            {"id": "paper_1", "label": "Paper", "name": "PMID:34567890", "group": "Paper", "properties": {"retracted": True}},
            {"id": "paper_2", "label": "Paper", "name": "PMID:34567891", "group": "Paper", "properties": {"pubpeer_flags": 12}},
            {"id": "paper_3", "label": "Paper", "name": "PMID:34567892", "group": "Paper", "properties": {}},
            
            # 临床试验
            {"id": "trial_1", "label": "ClinicalTrial", "name": "NCT04994483", "group": "ClinicalTrial", "properties": {}},
            {"id": "trial_2", "label": "ClinicalTrial", "name": "NCT02345678", "group": "ClinicalTrial", "properties": {}},
            
            # 不良事件
            {"id": "ae_1", "label": "AdverseEvent", "name": "Cardiotoxicity", "group": "AdverseEvent", "properties": {"severity": "high"}},
            {"id": "ae_2", "label": "AdverseEvent", "name": "Hepatotoxicity", "group": "AdverseEvent", "properties": {"severity": "medium"}},
            
            # 监管警告
            {"id": "warning_1", "label": "RegulatoryWarning", "name": "FDA Warning Letter 2023", "group": "RegulatoryWarning", "properties": {}},
            
            # 公司节点
            {"id": "company_1", "label": "Company", "name": "Cassava Sciences", "group": "Company", "properties": {"suspicious": True}},
            {"id": "company_2", "label": "Company", "name": "Merck", "group": "Company", "properties": {}},
        ],
        "links": [
            # 药物-作者关系（发现欺诈网络的关键）
            {"source": "drug_1", "target": "author_1", "type": "RESEARCHED_BY"},
            {"source": "drug_2", "target": "author_1", "type": "RESEARCHED_BY"},  # 🚨 同一作者为多个药物背书
            
            # 药物-论文关系
            {"source": "drug_1", "target": "paper_1", "type": "SUPPORTED_BY"},
            {"source": "drug_1", "target": "paper_2", "type": "SUPPORTED_BY"},
            
            # 作者-论文关系
            {"source": "author_1", "target": "paper_1", "type": "AUTHORED"},
            {"source": "author_2", "target": "paper_1", "type": "AUTHORED"},
            {"source": "author_1", "target": "paper_2", "type": "AUTHORED"},
            
            # 药物-临床试验关系
            {"source": "drug_1", "target": "trial_1", "type": "TESTED_IN"},
            {"source": "drug_2", "target": "trial_2", "type": "TESTED_IN"},
            
            # 药物-不良事件关系
            {"source": "drug_1", "target": "ae_1", "type": "CAUSES"},
            {"source": "drug_2", "target": "ae_1", "type": "CAUSES"},
            {"source": "drug_2", "target": "ae_2", "type": "CAUSES"},
            
            # 药物-公司关系
            {"source": "drug_1", "target": "company_1", "type": "PRODUCED_BY"},
            {"source": "drug_2", "target": "company_2", "type": "PRODUCED_BY"},
            
            # 公司-警告关系
            {"source": "company_1", "target": "warning_1", "type": "RECEIVED"},
        ],
        "timestamp": datetime.now().isoformat()
    }
    
    return mock_data


def _get_mock_drug_graph(drug_name: str) -> Dict[str, Any]:
    """返回模拟的特定药物图谱数据（返回字典，不是jsonify）"""
    mock_data = {
        "success": True,
        "source": "mock",
        "drug": drug_name,
        "nodes": [
            # 中心药物节点
            {"id": "drug_center", "label": "Drug", "name": drug_name, "group": "Drug", "isDrugCenter": True, "properties": {}},
            
            # 相关论文
            {"id": "paper_1", "label": "Paper", "name": f"Study of {drug_name}", "group": "Paper", "properties": {"year": 2023}},
            {"id": "paper_2", "label": "Paper", "name": f"{drug_name} efficacy trial", "group": "Paper", "properties": {"year": 2022}},
            
            # 作者
            {"id": "author_1", "label": "Author", "name": "Dr. Smith", "group": "Author", "properties": {}},
            {"id": "author_2", "label": "Author", "name": "Dr. Johnson", "group": "Author", "properties": {}},
            
            # 临床试验
            {"id": "trial_1", "label": "ClinicalTrial", "name": "NCT12345678", "group": "ClinicalTrial", "properties": {"phase": "III"}},
            
            # 不良事件
            {"id": "ae_1", "label": "AdverseEvent", "name": "Nausea", "group": "AdverseEvent", "properties": {"frequency": "common"}},
            {"id": "ae_2", "label": "AdverseEvent", "name": "Dizziness", "group": "AdverseEvent", "properties": {"frequency": "rare"}},
        ],
        "links": [
            {"source": "drug_center", "target": "paper_1", "type": "SUPPORTED_BY"},
            {"source": "drug_center", "target": "paper_2", "type": "SUPPORTED_BY"},
            {"source": "drug_center", "target": "trial_1", "type": "TESTED_IN"},
            {"source": "drug_center", "target": "ae_1", "type": "CAUSES"},
            {"source": "drug_center", "target": "ae_2", "type": "CAUSES"},
            {"source": "author_1", "target": "paper_1", "type": "AUTHORED"},
            {"source": "author_2", "target": "paper_1", "type": "AUTHORED"},
            {"source": "author_1", "target": "paper_2", "type": "AUTHORED"},
        ],
        "timestamp": datetime.now().isoformat()
    }
    
    return mock_data


# ============================================================================
# Routes: Configuration API
# ============================================================================

@app.route('/api/test-gemini', methods=['POST'])
def test_gemini():
    """
    POST /api/test-gemini
    
    Tests Google Gemini API connection.
    
    Request Body:
        {"api_key": "AIza..."}
    
    Response:
        {"success": true, "message": "Connection successful"}
    """
    try:
        data = request.json
        api_key = data.get('api_key')
        
        if not api_key:
            return jsonify({
                "success": False,
                "error": "API key required"
            }), 400
        
        # Test Gemini connection
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        # Use the configured model or fallback to gemini-2.5-flash (stable and fast)
        model_name = getattr(config, 'REPORT_MODEL_NAME', 'gemini-2.5-flash')
        model = genai.GenerativeModel(model_name)
        response = model.generate_content("Hello, test connection")
        
        return jsonify({
            "success": True,
            "message": "Gemini API connection successful",
            "test_response": response.text[:100]
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/test-neo4j', methods=['POST'])
def test_neo4j():
    """
    POST /api/test-neo4j
    
    Tests Neo4j database connection.
    
    Request Body:
        {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "password",
            "database": "neo4j"
        }
    
    Response:
        {"success": true, "message": "Connection successful"}
    """
    try:
        data = request.json
        
        from neo4j import GraphDatabase
        from neo4j import basic_auth
        
        driver = GraphDatabase.driver(
            data.get('uri'),
            auth=basic_auth(data.get('user'), data.get('password'))
        )
        
        # Test connection
        with driver.session(database=data.get('database', 'neo4j')) as session:
            result = session.run("RETURN 1 AS test")
            test_value = result.single()['test']
        
        driver.close()
        
        return jsonify({
            "success": True,
            "message": "Neo4j connection successful"
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
            "neo4j": {...},
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
            "neo4j": {...},
            "redis": {...}
        }
    """
    try:
        return jsonify({
            "gemini": {
                "model": getattr(config, 'REPORT_MODEL_NAME', 'gemini-3-pro-preview'),
                "temperature": getattr(config, 'REPORT_TEMPERATURE', 0.7),
                "max_tokens": getattr(config, 'REPORT_MAX_TOKENS', 8192)
            },
            "neo4j": {
                "uri": getattr(config, 'NEO4J_URI', 'bolt://localhost:7687'),
                "user": getattr(config, 'NEO4J_USER', 'neo4j'),
                "database": getattr(config, 'NEO4J_DATABASE', 'neo4j')
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


# ============================================================================
# Real-Time Graph Updates (实时图谱推送)
# ============================================================================

def emit_graph_node(node_type: str, node_name: str, properties: Dict = None):
    """
    🔥 实时推送新发现的节点到前端图谱
    
    当BioHarvestEngine或EvidenceEngine发现新的论文、作者、临床试验时，
    这个函数会立即通知前端，让图谱在评委眼前实时生长！
    
    Args:
        node_type: 节点类型 (Drug, Paper, Author, ClinicalTrial, AdverseEvent, etc.)
        node_name: 节点名称
        properties: 节点属性字典
        
    Example:
        emit_graph_node('Paper', 'PMID:34567890', {'title': '...', 'year': 2023})
    """
    try:
        node_data = {
            'id': f"{node_type}_{node_name.replace(':', '_').replace(' ', '_')}",
            'label': node_type,
            'name': node_name,
            'properties': properties or {},
            'group': node_type
        }
        
        socketio.emit('graph_update', {
            'type': 'node',
            'data': node_data,
            'timestamp': datetime.now().isoformat()
        })
        
        logger.info(f"📊 Graph Update: New {node_type} → {node_name}")
        
    except Exception as e:
        logger.error(f"Failed to emit graph node: {e}")


def emit_graph_relationship(source_type: str, source_name: str, 
                            target_type: str, target_name: str, 
                            relationship_type: str, properties: Dict = None):
    """
    🔥 实时推送新发现的关系到前端图谱
    
    当发现两个节点之间的关系时（如：Drug → CAUSES → AdverseEvent），
    这个函数会在图谱中绘制连接线。
    
    Args:
        source_type: 源节点类型
        source_name: 源节点名称
        target_type: 目标节点类型
        target_name: 目标节点名称
        relationship_type: 关系类型 (CAUSES, AUTHORED, TESTED_IN, etc.)
        properties: 关系属性字典
    """
    try:
        source_id = f"{source_type}_{source_name.replace(':', '_').replace(' ', '_')}"
        target_id = f"{target_type}_{target_name.replace(':', '_').replace(' ', '_')}"
        
        link_data = {
            'source': source_id,
            'target': target_id,
            'type': relationship_type,
            'properties': properties or {}
        }
        
        socketio.emit('graph_update', {
            'type': 'relationship',
            'data': link_data,
            'timestamp': datetime.now().isoformat()
        })
        
        logger.info(f"📊 Graph Update: {source_name} → {relationship_type} → {target_name}")
        
    except Exception as e:
        logger.error(f"Failed to emit graph relationship: {e}")


# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == '__main__':
    logger.info("="*80)
    logger.info("🧬 Cassandra - Biomedical Due Diligence Platform")
    logger.info("="*80)
    logger.info(f"🌐 Server: http://0.0.0.0:{config.PORT}")
    logger.info(f"📊 Neo4j Available: {NEO4J_AVAILABLE}")
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
