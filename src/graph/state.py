"""
Bio-Short-Seller Agent State

This module defines the shared state structure for the LangGraph workflow.
The state acts as shared memory passed between all agent nodes.
"""

from typing import TypedDict, List, Dict, Any, Optional, Annotated
import operator


class AgentState(TypedDict):
    """
    Shared state for the Bio-Short-Seller orchestration workflow.
    
    This state is passed between all nodes in the LangGraph pipeline,
    accumulating evidence from each specialized agent.
    
    Workflow State Progression:
        1. User provides query
        2. Harvester populates harvested_data and pdf_paths
        3. Miner (parallel) populates text_evidence
        4. Auditor (parallel) populates forensic_evidence
        5. GraphBuilder validates and prepares data
        6. Writer generates final_report
    
    🚨 PHASE 2 ADDITIONS: Failure tracking and honest reporting
        - compiled_evidence_text: Actual text content (not just counts)
        - failed_files: Files that failed during evidence mining
        - forensic_failed_files: Files that failed during forensic audit
        - total_files: Total PDFs attempted for analysis
        - risk_override: Forced risk level when data is incomplete
        - analysis_status: Overall analysis completeness status
    
    Attributes:
        user_query: Original user input (e.g., "Analyze drug X safety concerns")
        pdf_paths: List of PDF file paths to analyze (from Harvester or manual input)
        harvested_data: Literature and clinical trial metadata from BioHarvestEngine
        text_evidence: Dark data risk signals from EvidenceEngine (supplementary materials)
        forensic_evidence: Suspicious image findings from ForensicEngine
        final_report: Generated markdown report from ReportWriterAgent
        
        # 🚨 PHASE 2: Evidence text aggregation
        compiled_evidence_text: Aggregated text content of all evidence items
        
        # 🚨 PHASE 2: Failure tracking
        failed_files: List of filenames that failed evidence mining
        forensic_failed_files: List of filenames that failed forensic audit
        total_files: Total number of PDFs attempted for analysis
        all_failed_files: Combined list of all failed files (deduplicated)
        total_failed_files: Total count of unique failed files
        
        # 🚨 PHASE 2: Honest reporting metadata
        risk_override: Forced risk assessment when data is incomplete/missing
        analysis_status: COMPLETE | PARTIAL_SUCCESS | CRITICAL_FAILURE | NO_DATA
        
        # Optional metadata
        project_name: Drug/therapy name (auto-extracted or provided)
        status: Current workflow status (for tracking)
        errors: Any errors encountered during execution
        
    Note:
        - Lists that may be updated by parallel nodes use Annotated with operator.add
        - Single-value keys (user_query, project_name, etc.) use last-write-wins
    """
    # Core workflow data
    user_query: str  # Single value, last-write-wins
    pdf_paths: Annotated[List[str], operator.add]  # Can be accumulated
    harvested_data: Annotated[List[Dict[str, Any]], operator.add]  # Can be accumulated
    text_evidence: Annotated[List[Dict[str, Any]], operator.add]  # Parallel miner can add
    forensic_evidence: Annotated[List[Dict[str, Any]], operator.add]  # Parallel auditor can add
    final_report: Optional[str]  # Last-write-wins (markdown content)
    final_report_path: Optional[str]  # Last-write-wins (file path)
    final_report_markdown: Optional[str]  # Last-write-wins (duplicate for clarity)
    
    # 🚨 PHASE 2: Evidence text aggregation (bridges state gap)
    compiled_evidence_text: Optional[str]  # Last-write-wins
    
    # 🚨 PHASE 2: Failure tracking (enforces honesty)
    failed_files: Annotated[List[str], operator.add]  # Files that failed evidence mining
    forensic_failed_files: Annotated[List[str], operator.add]  # Files that failed forensic audit
    total_files: Optional[int]  # Last-write-wins
    all_failed_files: Annotated[List[str], operator.add]  # Combined failure list
    total_failed_files: Optional[int]  # Last-write-wins
    
    # 🚨 PHASE 2: Honest reporting metadata (anti-silent-failure)
    risk_override: Optional[str]  # Last-write-wins (e.g., "UNKNOWN (DATA MISSING)")
    analysis_status: Optional[str]  # Last-write-wins (e.g., "PARTIAL_SUCCESS")
    
    # Metadata
    project_name: Optional[str]  # Last-write-wins
    status: Optional[str]  # Last-write-wins
    recommendation: Optional[str]  # Last-write-wins (from report writer)
    risk_score: Optional[float]  # Last-write-wins (from report writer)
    
    # Accumulated errors from all nodes (allows parallel accumulation)
    errors: Annotated[List[str], operator.add]
