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
import markdown

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
app.config['TEMPLATES_AUTO_RELOAD'] = True  # Disable template caching for development
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable static file caching

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
                image_path = None
                
                if "ERROR" in message or "❌" in message or "CRITICAL" in message:
                    level = "error"
                elif "WARNING" in message or "⚠" in message:
                    level = "warning"
                elif "SUCCESS" in message or "✅" in message:
                    level = "success"
                elif "Scanning" in message or "Analyzing figure" in message or "🔍" in message:
                    level = "scanning"
                    
                    # Extract image path from message if present
                    import re
                    # Look for patterns like: figure_001.png, page_5_img_2.png, etc.
                    img_match = re.search(r'(figure_\d+|page_\d+_img_\d+)\.png', message)
                    if img_match:
                        # Construct relative path for web access
                        image_filename = img_match.group(0)
                        # Assuming images are in downloads/temp or similar
                        image_path = f'/static/temp/{image_filename}'
                
                # Extract clean message
                clean_msg = message.strip()
                
                # Emit to frontend with image path
                socketio.emit('log', {
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
        
        # Get all markdown and JSON files
        report_files = list(reports_dir.glob("*.md")) + list(reports_dir.glob("*.json"))
        
        # Sort by modification time (newest first)
        report_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        
        reports = []
        for report_path in report_files:
            stat = report_path.stat()
            
            # Extract title from filename
            title = report_path.stem.replace('_', ' ').title()
            
            # Try to read preview (first 200 chars)
            preview = ""
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    content = f.read(500)
                    # Extract first heading or first paragraph
                    lines = content.split('\n')
                    for line in lines:
                        if line.strip() and not line.startswith('#'):
                            preview = line.strip()[:200]
                            break
            except:
                pass
            
            reports.append({
                "filename": report_path.name,
                "title": title,
                "timestamp": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "size": stat.st_size,
                "preview": preview
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
        
        # If it's markdown, render it
        if filename.endswith('.md'):
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>{filename}</title>
                <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
                <script src="https://cdn.tailwindcss.com"></script>
                <style>
                    .prose {{ max-width: 900px; margin: 0 auto; }}
                    .prose h1 {{ font-size: 2rem; font-weight: bold; margin-top: 1.5rem; margin-bottom: 1rem; }}
                    .prose h2 {{ font-size: 1.5rem; font-weight: bold; margin-top: 1.25rem; margin-bottom: 0.75rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; }}
                    .prose h3 {{ font-size: 1.25rem; font-weight: 600; margin-top: 1rem; margin-bottom: 0.5rem; }}
                    .prose p {{ margin-bottom: 1rem; line-height: 1.6; }}
                    .prose ul, .prose ol {{ margin-left: 1.5rem; margin-bottom: 1rem; }}
                    .prose li {{ margin-bottom: 0.5rem; }}
                    .prose code {{ background-color: #f7fafc; padding: 0.2rem 0.4rem; border-radius: 0.25rem; font-family: monospace; }}
                    .prose pre {{ background-color: #2d3748; color: #e2e8f0; padding: 1rem; border-radius: 0.5rem; overflow-x: auto; }}
                    .prose table {{ width: 100%; border-collapse: collapse; margin-bottom: 1rem; }}
                    .prose th {{ background-color: #edf2f7; padding: 0.75rem; text-align: left; font-weight: bold; border: 1px solid #cbd5e0; }}
                    .prose td {{ padding: 0.75rem; border: 1px solid #e2e8f0; }}
                </style>
            </head>
            <body class="bg-gray-50 p-8">
                <div class="prose">
                    <div id="content"></div>
                </div>
                <script>
                    document.getElementById('content').innerHTML = marked.parse({json.dumps(content)});
                </script>
            </body>
            </html>
            """
        else:
            # For JSON or other formats, return as plain text
            return f"<pre>{content}</pre>"
        
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
    
    Downloads a specific report file, converting to PDF if it's a markdown file.
    """
    try:
        report_path = Path("final_reports") / filename
        
        if not report_path.exists():
            return jsonify({
                "success": False,
                "message": "Report not found"
            }), 404
        
        # If it's a markdown file, convert to PDF first
        if filename.endswith('.md'):
            try:
                pdf_path = convert_markdown_to_pdf(report_path)
                return send_file(
                    pdf_path,
                    as_attachment=True,
                    download_name=filename.replace('.md', '.pdf'),
                    mimetype='application/pdf'
                )
            except Exception as e:
                logger.error(f"PDF conversion failed, falling back to markdown: {e}")
                # Fall back to markdown if PDF conversion fails
                return send_file(
                    report_path,
                    as_attachment=True,
                    download_name=filename,
                    mimetype='text/markdown'
                )
        else:
            # For non-markdown files, serve as-is
            return send_file(
                report_path,
                as_attachment=True,
                download_name=filename
            )
        
    except Exception as e:
        logger.error(f"Failed to download report: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# ============================================================================
# Helper Functions: PDF Generation
# ============================================================================

def convert_markdown_to_pdf(markdown_path: Path) -> Path:
    """
    Convert a Markdown file to PDF using simple HTML rendering.
    
    Args:
        markdown_path: Path to the markdown file
        
    Returns:
        Path to the generated PDF file
    """
    try:
        # Try using reportlab if available
        try:
            from reportlab.lib.pagesizes import letter, A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
            from reportlab.lib.enums import TA_LEFT, TA_CENTER
            
            # Read markdown content
            with open(markdown_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
            
            # Convert markdown to HTML
            html_content = markdown.markdown(md_content, extensions=['tables', 'fenced_code', 'codehilite'])
            
            # Create PDF
            pdf_path = markdown_path.with_suffix('.pdf')
            doc = SimpleDocTemplate(str(pdf_path), pagesize=letter,
                                  topMargin=0.75*inch, bottomMargin=0.75*inch)
            
            # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], 
                                        fontSize=18, textColor='#1a202c', spaceAfter=12)
            normal_style = styles['Normal']
            
            # Build PDF content
            story = []
            
            # Simple text extraction (removing HTML tags for basic formatting)
            import re
            text_content = re.sub('<[^<]+?>', '', html_content)
            lines = text_content.split('\n')
            
            for line in lines:
                if line.strip():
                    if line.startswith('#'):
                        story.append(Paragraph(line.replace('#', '').strip(), title_style))
                        story.append(Spacer(1, 0.2*inch))
                    else:
                        story.append(Paragraph(line.strip(), normal_style))
                        story.append(Spacer(1, 0.1*inch))
            
            doc.build(story)
            logger.info(f"✅ PDF generated: {pdf_path}")
            return pdf_path
            
        except ImportError:
            logger.warning("reportlab not available, falling back to simple HTML rendering")
            # Fallback: create a simple PDF wrapper
            pdf_path = markdown_path.with_suffix('.pdf')
            # Copy markdown as text (fallback)
            import shutil
            shutil.copy(str(markdown_path), str(pdf_path))
            return pdf_path
            
    except Exception as e:
        logger.error(f"Failed to convert markdown to PDF: {e}")
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
    """
    GET /api/graph/global
    
    ⭐️ 方案 A：全局知识图谱（Global Brain）
    返回整个Neo4j数据库的知识图谱，展示所有药物、论文、不良事件、作者之间的关系。
    
    这是Cassandra的"长期记忆"——随着分析案例增多，自动构建生物医药欺诈网络。
    可以发现：
    - 不同公司雇佣同一个造假作者
    - 多个药物共享可疑的临床试验
    - 造假论文之间的引用网络
    
    Response:
        {
            "success": true,
            "source": "neo4j",
            "totalNodes": 1234,
            "totalRelationships": 5678,
            "nodes": [...],
            "links": [...]
        }
    """
    try:
        # 🔥 直接返回Mock数据，因为GraphManager.query()方法不存在
        # 未来需要在GraphManager中实现query()方法
        logger.info("📊 Returning mock global graph data")
        return jsonify(_get_mock_global_graph())
            
    except Exception as e:
        logger.error(f"Failed to fetch global graph: {e}")
        return jsonify(_get_mock_global_graph())


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
    """Client connected to SocketIO"""
    logger.info(f"🔌 Client connected: {request.sid}")
    emit('connected', {'message': 'Connected to Cassandra backend'})


@socketio.on('disconnect')
def handle_disconnect():
    """Client disconnected from SocketIO"""
    logger.info(f"🔌 Client disconnected: {request.sid}")


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
