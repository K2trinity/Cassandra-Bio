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
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from loguru import logger

# Import configuration
from config import Settings

# Import the core LangGraph workflow
from src.agents.supervisor import run_bio_short_seller
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
    "error": None
}


# ============================================================================
# Logging Configuration
# ============================================================================

# Configure loguru for beautiful console output
logger.remove()  # Remove default handler
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)

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
# Custom Logger Interceptor for SocketIO Streaming
# ============================================================================

class SocketIOLogHandler:
    """
    Custom log handler that emits logs to connected SocketIO clients
    in real-time during workflow execution.
    """
    
    def write(self, message: str):
        if message.strip() and active_analysis["running"]:
            try:
                # Parse log level from message
                level = "info"
                if "ERROR" in message or "❌" in message:
                    level = "error"
                elif "WARNING" in message or "⚠" in message:
                    level = "warning"
                elif "SUCCESS" in message or "✅" in message:
                    level = "success"
                
                # Extract clean message
                clean_msg = message.strip()
                
                # Emit to frontend
                socketio.emit('log', {
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
def index():
    """Mission Control - Main Dashboard"""
    return render_template('index.html')


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
    global active_analysis
    
    # Check if analysis is already running
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
    active_analysis = {
        "running": True,
        "query": query,
        "thread": None,
        "result": None,
        "error": None
    }
    
    # Define background task
    def run_analysis_async():
        """Execute LangGraph workflow in background thread"""
        global active_analysis
        
        try:
            # Emit progress: Starting
            socketio.emit('step', {'step': 'harvest', 'status': 'active'})
            logger.info("🔬 Starting Bio-Short-Seller workflow...")
            
            # Execute LangGraph workflow
            result = run_bio_short_seller(
                user_query=query,
                pdf_paths=pdf_paths if pdf_paths else None
            )
            
            # Store result
            active_analysis["result"] = result
            active_analysis["running"] = False
            
            # Extract full report content for frontend display
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
            
            # Emit completion with FULL markdown content
            socketio.emit('step', {'step': 'writing', 'status': 'complete'})
            socketio.emit('analysis_complete', {
                'success': True,
                'report_path': report_path,
                'full_report_markdown': full_report_markdown,  # NEW: Send complete Markdown
                'executive_summary': full_report_markdown[:1500] if full_report_markdown else "",  # Backward compatibility
                'summary': {
                    'harvested_items': len(result.get('harvested_data', [])),
                    'text_evidence': len(result.get('text_evidence', [])),
                    'forensic_evidence': len(result.get('forensic_evidence', []))
                }
            })
            
            logger.info("✅ Analysis complete!")
            
        except Exception as e:
            logger.error(f"❌ Analysis failed: {e}")
            import traceback
            error_trace = traceback.format_exc()
            logger.error(error_trace)
            
            active_analysis["error"] = str(e)
            active_analysis["running"] = False
            
            socketio.emit('analysis_error', {
                'success': False,
                'error': str(e)
            })
    
    # Start background thread
    analysis_thread = threading.Thread(target=run_analysis_async, daemon=True)
    analysis_thread.start()
    active_analysis["thread"] = analysis_thread
    
    return jsonify({
        "status": "accepted",
        "message": "Analysis started. Monitor progress via WebSocket.",
        "query": query
    }), 202


@app.route('/api/status', methods=['GET'])
def get_status():
    """
    GET /api/status
    
    Returns the current status of the analysis workflow.
    
    Response:
        {
            "running": true/false,
            "query": "...",
            "error": null or "error message"
        }
    """
    return jsonify({
        "running": active_analysis["running"],
        "query": active_analysis["query"],
        "error": active_analysis["error"]
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


@app.route('/api/reports/download/<filename>', methods=['GET'])
def download_report(filename: str):
    """
    GET /api/reports/download/<filename>
    
    Downloads a specific report file.
    """
    try:
        report_path = Path("final_reports") / filename
        
        if not report_path.exists():
            return jsonify({
                "success": False,
                "message": "Report not found"
            }), 404
        
        return send_file(
            report_path,
            as_attachment=True,
            download_name=filename,
            mimetype='text/markdown'
        )
        
    except Exception as e:
        logger.error(f"Failed to download report: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


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
    """Client connected to SocketIO"""
    logger.info(f"🔌 Client connected: {request.sid}")
    emit('connected', {'message': 'Connected to Cassandra backend'})


@socketio.on('disconnect')
def handle_disconnect():
    """Client disconnected from SocketIO"""
    logger.info(f"🔌 Client disconnected: {request.sid}")


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
