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
    
    Attributes:
        user_query: Original user input (e.g., "Analyze drug X safety concerns")
        pdf_paths: List of PDF file paths to analyze (from Harvester or manual input)
        harvested_data: Literature and clinical trial metadata from BioHarvestEngine
        text_evidence: Dark data risk signals from EvidenceEngine (supplementary materials)
        forensic_evidence: Suspicious image findings from ForensicEngine
        final_report: Generated markdown report from ReportWriterAgent
        
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
    final_report: Optional[str]  # Last-write-wins
    
    # Metadata
    project_name: Optional[str]  # Last-write-wins
    status: Optional[str]  # Last-write-wins
    
    # Accumulated errors from all nodes (allows parallel accumulation)
    errors: Annotated[List[str], operator.add]
