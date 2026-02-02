"""
Bio-Short-Seller Supervisor - LangGraph Orchestration

This module orchestrates all specialized agents using LangGraph.

Workflow:
    User Input
        ↓
    Harvester (BioHarvestEngine)
        ↓
    [Parallel Execution]
        ├→ Miner (EvidenceEngine)
        └→ Auditor (ForensicEngine)
        ↓
    GraphBuilder (Data Aggregation & Validation)
        ↓
    Writer (ReportWriterAgent)
        ↓
    Final Report
"""

import os
from pathlib import Path
from typing import Dict, Any
from loguru import logger

from langgraph.graph import StateGraph, START, END

from src.graph.state import AgentState
from BioHarvestEngine.agent import BioHarvestAgent
from ForensicEngine.agent import ForensicAuditorAgent
from EvidenceEngine.agent import create_agent as create_evidence_agent
from src.agents.report_writer import create_agent as create_report_agent


# ========== Node Implementations ==========

def harvester_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 1: BioHarvestEngine - Literature & Clinical Trial Harvester
    
    Searches PubMed and ClinicalTrials.gov for relevant papers and trials.
    Extracts PDF links and metadata for downstream analysis.
    
    Args:
        state: Current workflow state with user_query
    
    Returns:
        Updated state with:
            - harvested_data: List of papers/trials
            - pdf_paths: List of PDF URLs/paths (if available)
    """
    logger.info("\n" + "="*80)
    logger.info("🔬 NODE 1: BIO-HARVEST ENGINE")
    logger.info("="*80)
    
    try:
        agent = BioHarvestAgent()
        
        # Run harvest
        results = agent.run(
            user_query=state["user_query"],
            max_results_per_source=20
        )
        
        # Extract LOCAL PDF paths from downloaded papers
        # BioHarvestEngine now includes 'local_path' field after downloading PMC PDFs
        pdf_paths = []
        for result in results.get("results", []):
            local_path = result.get("local_path")
            if local_path and os.path.exists(local_path):
                pdf_paths.append(local_path)
        
        logger.success(f"✅ Harvested {len(results.get('results', []))} papers/trials")
        logger.info(f"📄 Found {len(pdf_paths)} valid local PDFs for analysis")
        
        return {
            "harvested_data": results.get("results", []),
            "pdf_paths": pdf_paths,  # Now contains local file paths, not URLs
            "status": "harvest_complete"
        }
        
    except Exception as e:
        logger.error(f"❌ Harvester failed: {e}")
        return {
            "harvested_data": [],
            "pdf_paths": [],
            "errors": [f"Harvester: {str(e)}"],
            "status": "harvest_failed"
        }


def miner_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 2A: EvidenceEngine - Dark Data Miner (Parallel)
    
    Analyzes PDF supplementary materials for buried negative results.
    Runs in parallel with ForensicEngine.
    
    Args:
        state: Current workflow state with pdf_paths
    
    Returns:
        Updated state with:
            - text_evidence: List of EvidenceItem dicts
    """
    logger.info("\n" + "="*80)
    logger.info("🕵️ NODE 2A: EVIDENCE MINER (Parallel)")
    logger.info("="*80)
    
    try:
        agent = create_evidence_agent()
        
        pdf_paths = state.get("pdf_paths", [])
        
        if not pdf_paths:
            logger.warning("⚠️ No PDFs provided for evidence mining")
            return {
                **state,
                "text_evidence": [],
                "status": "mining_skipped"
            }
        
        # Mine evidence from all PDFs
        all_evidence = []
        for i, pdf_path in enumerate(pdf_paths[:3], 1):  # Limit to first 3 PDFs
            logger.info(f"\n📄 Mining PDF {i}/{min(3, len(pdf_paths))}: {pdf_path}")
            
            try:
                # pdf_path is now a local file path (downloaded by BioHarvestEngine)
                if os.path.exists(pdf_path):
                    evidence_items = agent.mine_evidence(pdf_path)
                    
                    # Convert EvidenceItem dataclasses to dicts
                    evidence_dicts = [
                        {
                            "source": e.source,
                            "page_estimate": e.page_estimate,
                            "quote": e.quote,
                            "risk_level": e.risk_level,
                            "risk_type": e.risk_type,
                            "explanation": e.explanation
                        }
                        for e in evidence_items
                    ]
                    
                    all_evidence.extend(evidence_dicts)
                else:
                    logger.warning(f"PDF not found locally: {pdf_path}")
            
            except Exception as e:
                logger.error(f"Failed to mine PDF {i}: {e}")
                continue
        
        logger.success(f"✅ Mined {len(all_evidence)} evidence items from {min(3, len(pdf_paths))} PDFs")
        
        return {
            "text_evidence": all_evidence
        }
        
    except Exception as e:
        logger.error(f"❌ Evidence Miner failed: {e}")
        return {
            "text_evidence": [],
            "errors": [f"Miner: {str(e)}"]
        }


def auditor_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 2B: ForensicEngine - Image Forensic Auditor (Parallel)
    
    Analyzes scientific figures for potential manipulation.
    Runs in parallel with EvidenceEngine.
    
    Args:
        state: Current workflow state with pdf_paths
    
    Returns:
        Updated state with:
            - forensic_evidence: List of ImageAuditResult dicts
    """
    logger.info("\n" + "="*80)
    logger.info("🔍 NODE 2B: FORENSIC AUDITOR (Parallel)")
    logger.info("="*80)
    
    try:
        agent = ForensicAuditorAgent()
        
        pdf_paths = state.get("pdf_paths", [])
        
        if not pdf_paths:
            logger.warning("⚠️ No PDFs provided for forensic audit")
            return {
                "forensic_evidence": []
            }
        
        # Audit all PDFs
        all_audit_results = []
        for i, pdf_path in enumerate(pdf_paths[:3], 1):  # Limit to first 3 PDFs
            logger.info(f"\n📄 Auditing PDF {i}/{min(3, len(pdf_paths))}: {pdf_path}")
            
            try:
                if os.path.exists(pdf_path):
                    audit_results = agent.audit_paper(pdf_path)
                    
                    # Convert ImageAuditResult dataclasses to dicts
                    audit_dicts = [
                        {
                            "image_id": r.image_id,
                            "image_path": r.image_path,
                            "page_num": r.page_num,
                            "status": r.status,
                            "tampering_risk_score": r.tampering_risk_score,
                            "findings": r.findings,
                            "raw_analysis": r.raw_analysis
                        }
                        for r in audit_results
                    ]
                    
                    all_audit_results.extend(audit_dicts)
                else:
                    logger.warning(f"PDF not found locally: {pdf_path}")
            
            except Exception as e:
                logger.error(f"Failed to audit PDF {i}: {e}")
                continue
        
        logger.success(f"✅ Audited {len(all_audit_results)} images from {min(3, len(pdf_paths))} PDFs")
        
        return {
            "forensic_evidence": all_audit_results
        }
        
    except Exception as e:
        logger.error(f"❌ Forensic Auditor failed: {e}")
        return {
            "forensic_evidence": [],
            "errors": [f"Auditor: {str(e)}"],
            "status": "audit_failed"
        }


def graph_builder_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 3: Graph Builder - Data Aggregation & Validation
    
    Waits for both Miner and Auditor to complete, then validates
    and prepares data for the Report Writer.
    
    This node acts as a synchronization point and can optionally
    build knowledge graphs or perform additional data structuring.
    
    Args:
        state: Current workflow state with text_evidence and forensic_evidence
    
    Returns:
        Updated state with validated data
    """
    logger.info("\n" + "="*80)
    logger.info("🧩 NODE 3: GRAPH BUILDER (Data Aggregation)")
    logger.info("="*80)
    
    try:
        # Validate data presence
        harvested_count = len(state.get("harvested_data", []))
        text_evidence_count = len(state.get("text_evidence", []))
        forensic_count = len(state.get("forensic_evidence", []))
        
        logger.info(f"📊 Data Summary:")
        logger.info(f"   - Harvested Papers/Trials: {harvested_count}")
        logger.info(f"   - Text Evidence Items: {text_evidence_count}")
        logger.info(f"   - Forensic Audit Results: {forensic_count}")
        
        # Extract project name from query if not set
        project_name = state.get("project_name")
        if not project_name:
            # Simple extraction: first capitalized word sequence
            words = state["user_query"].split()
            project_name = " ".join(words[:3]) if words else "Unknown"
        
        # Validate minimum data requirements
        if harvested_count == 0:
            logger.warning("⚠️ No harvested data available")
        
        if text_evidence_count == 0 and forensic_count == 0:
            logger.warning("⚠️ No evidence data available (neither text nor forensic)")
        
        logger.success("✅ Data aggregation complete - ready for report generation")
        
        return {
            "project_name": project_name,
            "status": "graph_complete"
        }
        
    except Exception as e:
        logger.error(f"❌ Graph Builder failed: {e}")
        return {
            "errors": [f"GraphBuilder: {str(e)}"],
            "status": "graph_failed"
        }


def writer_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 4: ReportWriter - Final Report Synthesis
    
    Synthesizes all evidence into a comprehensive biomedical due diligence report.
    
    Args:
        state: Current workflow state with all evidence data
    
    Returns:
        Updated state with:
            - final_report: Generated markdown report
    """
    logger.info("\n" + "="*80)
    logger.info("📝 NODE 4: REPORT WRITER")
    logger.info("="*80)
    
    try:
        agent = create_report_agent()
        
        # Prepare data for report writer
        harvest_data = {
            "query": state["user_query"],
            "results": state.get("harvested_data", [])
        }
        
        forensic_data = state.get("forensic_evidence", [])
        evidence_data = state.get("text_evidence", [])
        
        # Generate report
        report_output = agent.write_report(
            user_query=state["user_query"],
            harvest_data=harvest_data,
            forensic_data=forensic_data,
            evidence_data=evidence_data,
            project_name=state.get("project_name"),
            output_dir="final_reports"
        )
        
        logger.success(f"✅ Report generated successfully")
        logger.info(f"   Recommendation: {report_output.recommendation}")
        logger.info(f"   Risk Score: {report_output.risk_score:.1f}/10")
        
        return {
            "final_report": report_output.markdown_content,
            "status": "complete"
        }
        
    except Exception as e:
        logger.error(f"❌ Report Writer failed: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            "final_report": f"# Report Generation Failed\n\nError: {str(e)}",
            "errors": [f"Writer: {str(e)}"],
            "status": "writer_failed"
        }


# ========== Graph Construction ==========

def create_bio_short_seller_workflow() -> StateGraph:
    """
    Create the Bio-Short-Seller LangGraph workflow.
    
    Workflow Architecture:
        START
          ↓
        Harvester (BioHarvestEngine)
          ↓
        ┌─────────────┐
        ↓             ↓
      Miner       Auditor  (Parallel Execution)
    (Evidence)  (Forensic)
        ↓             ↓
        └─────────────┘
          ↓
        GraphBuilder (Sync & Validate)
          ↓
        Writer (ReportWriter)
          ↓
        END
    
    Returns:
        Compiled LangGraph application
    """
    logger.info("🏗️ Building Bio-Short-Seller workflow...")
    
    # Initialize state graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("harvester", harvester_node)
    workflow.add_node("miner", miner_node)
    workflow.add_node("auditor", auditor_node)
    workflow.add_node("graph_builder", graph_builder_node)
    workflow.add_node("writer", writer_node)
    
    # Define edges
    # START -> Harvester
    workflow.add_edge(START, "harvester")
    
    # Harvester -> Parallel execution (Miner + Auditor)
    workflow.add_edge("harvester", "miner")
    workflow.add_edge("harvester", "auditor")
    
    # Parallel nodes -> GraphBuilder (synchronization point)
    workflow.add_edge("miner", "graph_builder")
    workflow.add_edge("auditor", "graph_builder")
    
    # GraphBuilder -> Writer
    workflow.add_edge("graph_builder", "writer")
    
    # Writer -> END
    workflow.add_edge("writer", END)
    
    logger.success("✅ Workflow graph constructed")
    
    return workflow


def compile_workflow():
    """
    Compile the Bio-Short-Seller workflow.
    
    Returns:
        Compiled LangGraph application ready for execution
    """
    workflow = create_bio_short_seller_workflow()
    app = workflow.compile()
    
    logger.success("✅ Workflow compiled successfully")
    
    return app


# ========== Workflow Execution ==========

def run_bio_short_seller(user_query: str, pdf_paths: list = None) -> Dict[str, Any]:
    """
    Execute the Bio-Short-Seller workflow end-to-end.
    
    Args:
        user_query: User's research question (e.g., "Analyze CAR-T therapy X safety")
        pdf_paths: Optional list of local PDF paths to analyze
    
    Returns:
        Final state dictionary with all results
    
    Example:
        >>> result = run_bio_short_seller(
        ...     user_query="Investigate pembrolizumab cardiotoxicity",
        ...     pdf_paths=["paper1.pdf", "paper2.pdf"]
        ... )
        >>> print(result["final_report"])
    """
    logger.info("\n" + "🚀"*40)
    logger.info("BIO-SHORT-SELLER WORKFLOW INITIATED")
    logger.info("🚀"*40 + "\n")
    
    # Compile workflow
    app = compile_workflow()
    
    # Initialize state
    initial_state: AgentState = {
        "user_query": user_query,
        "pdf_paths": pdf_paths or [],
        "harvested_data": [],
        "text_evidence": [],
        "forensic_evidence": [],
        "final_report": None,
        "project_name": None,
        "status": "initialized",
        "errors": []
    }
    
    # Execute workflow
    logger.info(f"📋 Query: {user_query}")
    logger.info(f"📄 Pre-loaded PDFs: {len(pdf_paths or [])}\n")
    
    try:
        # Run the workflow
        final_state = app.invoke(initial_state)
        
        logger.info("\n" + "="*80)
        logger.info("✅ WORKFLOW COMPLETE")
        logger.info("="*80)
        
        # Display summary
        logger.info(f"\n📊 Final Summary:")
        logger.info(f"   Status: {final_state.get('status', 'unknown')}")
        logger.info(f"   Harvested Items: {len(final_state.get('harvested_data', []))}")
        logger.info(f"   Text Evidence: {len(final_state.get('text_evidence', []))}")
        logger.info(f"   Forensic Evidence: {len(final_state.get('forensic_evidence', []))}")
        logger.info(f"   Report Generated: {'Yes' if final_state.get('final_report') else 'No'}")
        
        if final_state.get("errors"):
            logger.warning(f"   Errors Encountered: {len(final_state['errors'])}")
            for error in final_state["errors"]:
                logger.warning(f"     - {error}")
        
        return final_state
        
    except Exception as e:
        logger.error(f"\n❌ Workflow execution failed: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    # Test the workflow
    test_query = "Analyze CAR-T therapy safety concerns"
    result = run_bio_short_seller(test_query)
    
    if result.get("final_report"):
        print("\n" + "="*80)
        print("FINAL REPORT (Preview):")
        print("="*80)
        print(result["final_report"][:500] + "...")
