"""
Cassandra Agent State — Disease-Oriented Literature Review

This module defines the shared state structure for the LangGraph workflow.
The state acts as shared memory passed between all agent nodes.
"""

from typing import TypedDict, List, Dict, Any, Optional, Annotated
import operator

def add_or_replace_list(left: list, right: Any) -> list:
    if left is None: left = []
    if right is None: return left
    if isinstance(right, dict) and "$replace" in right:
        return right["$replace"]
    if isinstance(right, list):
        return left + right
    return left + [right]


class AgentState(TypedDict):
    """
    Shared state for the Cassandra disease-oriented literature review workflow.

    This state is passed between all nodes in the LangGraph pipeline,
    accumulating findings from each specialized agent.

    Workflow State Progression:
        1. User provides disease/therapy query
        2. Harvester populates harvested_data and pdf_paths
        3. Extension handoff prepares agent slots (slot_a, slot_b, slot_c)
        4. Writer consumes payload and generates report

    Attributes:
        user_query: Original user input (e.g., "Alzheimer's Disease treatment landscape")
        pdf_paths: List of PDF file paths to analyze (from Harvester or manual input)
        harvested_data: Literature and clinical trial metadata from Harvest
        final_report: Generated markdown report from ReportWriterAgent

        project_name: Drug/therapy name (auto-extracted or provided)
        status: Current workflow status (for tracking)
        errors: Any errors encountered during execution

        # Disease-oriented synthesis payload
        analysis_focus: Fixed analysis orientation marker
        biomedical_profile: Aggregated disease/drug/target/company/clinical summary
        disease_areas: Normalized disease/condition list
        drug_baselines: Normalized baseline drug/intervention list
        target_signals: Ranked target distribution summary
        company_entities: Ranked sponsor/company summary
        clinical_data: Clinical trial aggregate payload
        evidence_stats: Evidence volume summary

    Note:
        - Lists that may be updated by parallel nodes use Annotated with operator.add
        - Single-value keys (user_query, project_name, etc.) use last-write-wins
    """
    # Core workflow data
    user_query: str  # Single value, last-write-wins
    pdf_paths: Annotated[List[str], operator.add]  # Can be accumulated
    harvested_data: Annotated[List[Dict[str, Any]], add_or_replace_list]  # Can be accumulated
    harvest_data_layers: Optional[Dict[str, Any]]  # Last-write-wins
    harvest_source_payloads: Optional[Dict[str, Any]]  # Last-write-wins
    harvest_frontend_payload: Optional[Dict[str, Any]]  # Last-write-wins
    extension_payloads: Optional[Dict[str, Any]]  # Last-write-wins
    dataflow_contract_version: Optional[str]  # Last-write-wins
    final_report: Optional[str]  # Last-write-wins (markdown content)
    final_report_path: Optional[str]  # Last-write-wins (file path)
    final_report_markdown: Optional[str]  # Last-write-wins (duplicate for clarity)
    assessment_override: Optional[str]  # Last-write-wins
    analysis_status: Optional[str]  # Last-write-wins
    
    # Metadata
    project_name: Optional[str]  # Last-write-wins
    status: Optional[str]  # Last-write-wins
    analysis_focus: Optional[str]  # Last-write-wins
    biomedical_profile: Optional[Dict[str, Any]]  # Last-write-wins
    disease_areas: Optional[List[str]]  # Last-write-wins
    drug_baselines: Optional[List[str]]  # Last-write-wins
    target_signals: Optional[List[Dict[str, Any]]]  # Last-write-wins
    company_entities: Optional[List[Dict[str, Any]]]  # Last-write-wins
    clinical_data: Optional[Dict[str, Any]]  # Last-write-wins
    evidence_stats: Optional[Dict[str, Any]]  # Last-write-wins
    
    # Accumulated errors from all nodes (allows parallel accumulation)
    errors: Annotated[List[str], operator.add]
