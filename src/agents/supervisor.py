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
import json
from pathlib import Path
from typing import Dict, Any
from loguru import logger

from langgraph.graph import StateGraph, START, END

from src.graph.state import AgentState
from config import settings
from BioHarvestEngine.agent import BioHarvestAgent
from ForensicEngine.agent import ForensicAuditorAgent
from EvidenceEngine.agent import create_agent as create_evidence_agent
from src.agents.report_writer import create_agent as create_report_agent
from src.agents.smart_context_builder import create_smart_context_builder

# Import SocketIO functions for real-time graph updates
try:
    from flask import current_app
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    logger.warning("Flask not available in supervisor context")


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
        
        # 🔥 Real-time graph updates: Push harvested papers to frontend
        if FLASK_AVAILABLE:
            try:
                socketio = current_app.extensions.get('socketio')
                if socketio:
                    for result in results.get("results", [])[:10]:  # First 10 for demo
                        # Emit paper node
                        paper_id = result.get('pmid') or result.get('nct_id') or result.get('doi')
                        if paper_id:
                            socketio.emit('graph_update', {
                                'type': 'node',
                                'data': {
                                    'id': f"Paper_{paper_id}",
                                    'label': 'Paper',
                                    'name': paper_id,
                                    'properties': {
                                        'title': result.get('title', 'Unknown'),
                                        'year': result.get('year', 'N/A')
                                    },
                                    'group': 'Paper'
                                },
                                'timestamp': result.get('timestamp', '')
                            })
                            
                        # Emit authors
                        for author in result.get('authors', [])[:3]:  # First 3 authors
                            socketio.emit('graph_update', {
                                'type': 'node',
                                'data': {
                                    'id': f"Author_{author}",
                                    'label': 'Author',
                                    'name': author,
                                    'properties': {},
                                    'group': 'Author'
                                },
                                'timestamp': result.get('timestamp', '')
                            })
                            
                            # Emit relationship
                            if paper_id:
                                socketio.emit('graph_update', {
                                    'type': 'relationship',
                                    'data': {
                                        'source': f"Author_{author}",
                                        'target': f"Paper_{paper_id}",
                                        'type': 'AUTHORED',
                                        'properties': {}
                                    },
                                    'timestamp': result.get('timestamp', '')
                                })
                    logger.info("📊 Graph updates pushed to frontend")
            except Exception as e:
                logger.debug(f"Could not emit graph updates: {e}")
        
        return {
            "harvested_data": results.get("results", []),
            "pdf_paths": pdf_paths,  # Now contains local file paths, not URLs
            "pdf_files": pdf_paths,  # 🔥 STEP 3: Store as pdf_files for global tracking
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
            - compiled_evidence_text: Aggregated text content for ReportWriter
            - failed_files: List of files that failed to process
            - total_files: Total number of PDFs attempted
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
                "compiled_evidence_text": "",
                "failed_files": [],
                "total_files": 0,
                "status": "mining_skipped"
            }
        
        # 🚨 STEP 2 FIX: Initialize accumulators with explicit naming
        all_evidence = []
        all_evidence_context = []  # 🔥 RENAMED: Store actual evidence text content
        failed_files = []  # Track failed file processing
        
        # 🔥 FIXED: Use configurable PDF limit instead of hardcoded [:3]
        max_pdfs = settings.MAX_PDFS_TO_PROCESS if settings.MAX_PDFS_TO_PROCESS > 0 else len(pdf_paths)
        total_files = min(max_pdfs, len(pdf_paths))
        total_available = len(pdf_paths)
        
        logger.info(f"📊 PDF Processing Config: Processing {total_files} out of {total_available} available PDFs")
        
        # Mine evidence from all PDFs (up to configured limit)
        for i, pdf_path in enumerate(pdf_paths[:total_files], 1):
            logger.info(f"\n📄 Mining PDF {i}/{total_files} (Total available: {total_available}): {pdf_path}")
            
            try:
                # pdf_path is now a local file path (downloaded by BioHarvestEngine)
                if os.path.exists(pdf_path):
                    # 🔥 NEW PROTOCOL: mine_evidence now returns Dict with paper_summary and risk_signals
                    result = agent.mine_evidence(pdf_path)
                    
                    # --- 🔥 DEBUG BLOCK START ---
                    print(f"\n🔥 DEBUG: Inspecting Miner Result for PDF {i}")
                    print(f"🔥 DEBUG: Result Type: {type(result)}")
                    print(f"🔥 DEBUG: Available Keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
                    # --- 🔥 DEBUG BLOCK END ---
                    
                    # ============ ROBUST PROTOCOL: NORMALIZE INPUT ============
                    # 1. Handle Failed/Null Results
                    if result is None:
                        logger.error(f"❌ Received None result for {os.path.basename(pdf_path)}")
                        failed_files.append(os.path.basename(pdf_path))
                        continue
                    
                    # 2. Normalize Input (Handle Object vs Dict vs List)
                    # EXTRACT DATA (Handle Dict/Object)
                    data = result.__dict__ if hasattr(result, '__dict__') else result
                    if not isinstance(data, dict): 
                        if isinstance(data, list):
                            # Legacy/Fallback case: It's just a list of risks
                            logger.warning(f"⚠️ Legacy List Format detected")
                            data = {"paper_summary": "Summary not extracted (Legacy List).", "risk_signals": data, "filename": os.path.basename(pdf_path)}
                        else:
                            data = {}
                    
                    # 3. CRITICAL: Extract Summary & Risks with validation
                    # Check multiple keys to be safe
                    filename = data.get('filename', os.path.basename(pdf_path))
                    summary = data.get('paper_summary') or data.get('summary') or data.get('scientific_summary') or "[CRITICAL WARNING: CONTENT MISSING]"
                    risks = data.get('risk_signals') or data.get('risk_flags') or []
                    
                    # 🔥 NEW: Validate data quality before aggregation
                    # Skip files with errors or insufficient data
                    if summary.startswith("Error:") or "CONTENT MISSING" in summary:
                        logger.error(f"⚠️ Skipping {filename}: Error in summary - {summary[:100]}")
                        failed_files.append(filename)
                        continue
                    
                    # Check minimum content threshold (at least 200 characters)
                    if len(summary) < 200:
                        logger.warning(f"⚠️ {filename} has insufficient summary: {len(summary)} chars")
                        if len(risks) == 0:
                            logger.error(f"⚠️ Skipping {filename}: No risks and short summary")
                            failed_files.append(filename)
                            continue
                    
                    # Check for empty risks (at least warn)
                    if len(risks) == 0:
                        logger.warning(f"⚠️ {filename} has no risk signals detected")
                    
                    # 🔥 NEW: Track content quality metrics
                    logger.debug(f"✅ {filename}: {len(summary)} chars, {len(risks)} risks")
                    
                    # 4. FORCE CONCATENATION - Build rich context payload
                    # 🔥 FIX: Ensure filename is properly included in the entry
                    entry = f"""
=== EVIDENCE SOURCE: {filename} ===
> **FILE**: {filename}
> **SUMMARY**: {summary}
> **RISK FINDINGS**: {json.dumps(risks, indent=2)}
--------------------------------------------------
"""
                    all_evidence_context.append(entry)
                    # 🔥 FIX: Inject filename into each risk item to prevent "Unknown" plague
                    evidence_dicts = []
                    for risk in risks:
                        if hasattr(risk, '__dict__'):
                            risk_dict = {
                                "source": risk.source,
                                "page_estimate": risk.page_estimate,
                                "quote": risk.quote,
                                "risk_level": risk.risk_level,
                                "risk_type": risk.risk_type,
                                "explanation": risk.explanation,
                                "filename": filename  # 🔥 ADD: Filename tracking
                            }
                        else:
                            risk_dict = dict(risk) if isinstance(risk, dict) else {}
                            risk_dict["filename"] = filename  # 🔥 ADD: Filename tracking
                        
                        evidence_dicts.append(risk_dict)
                    
                    all_evidence.extend(evidence_dicts)
                    logger.success(f"✅ Extracted {len(risks)} findings from PDF {i}")
                        
                else:
                    # 🚨 PHASE 2 FIX: Track missing files as failures
                    logger.error(f"❌ PDF not found locally: {pdf_path}")
                    failed_files.append(os.path.basename(pdf_path))
            
            except Exception as e:
                # 🚨 PHASE 2 FIX: Catch failures and track them explicitly
                logger.error(f"❌ Failed to mine PDF {i}: {e}")
                import traceback
                traceback.print_exc()
                failed_files.append(os.path.basename(pdf_path))
                continue
        
        # Calculate success/failure metrics
        success_count = total_files - len(failed_files)
        logger.success(f"✅ Mined {len(all_evidence)} evidence items from {success_count}/{total_files} PDFs")
        
        if failed_files:
            logger.warning(f"⚠️ Failed to process {len(failed_files)} files: {', '.join(failed_files)}")
        
        # 🧠 DISABLED: Smart Context Builder - causing over-compression (91% loss)
        # 🚨 DEBUG FIX: Use original evidence text to prevent hallucinations
        logger.info("\n⚠️ Using ORIGINAL evidence text (Smart Context Builder disabled for debugging)")
        
        # Get forensic data for context optimization (if available in state)
        forensic_data = state.get("forensic_evidence", [])
        
        # 🔥 FIX: Use original uncompressed evidence text
        original_evidence_text = ''.join(all_evidence_context)
        optimized_context = original_evidence_text
        
        # Calculate basic stats
        stats = {
            'total_chars': len(optimized_context),
            'total_tokens': len(optimized_context) // 4,  # Rough estimate
            'compression_ratio': 1.0,  # No compression
            'critical_count': sum(1 for e in all_evidence if e.get('risk_level') in ['CRITICAL', 'HIGH']),
            'medium_count': sum(1 for e in all_evidence if e.get('risk_level') == 'MEDIUM'),
            'clean_count': 0
        }
        
        # Log results
        logger.success(f"📊 Evidence Context Prepared:")
        logger.info(f"   Total Size: {stats['total_chars']:,} chars ({stats['total_tokens']:,} tokens)")
        logger.info(f"   Compression: NONE (using original text)")
        logger.info(f"   Critical Items: {stats['critical_count']}")
        logger.info(f"   Medium Items: {stats['medium_count']}")
        logger.info(f"   Evidence Items: {len(all_evidence)}")
        
        # ===== ORIGINAL SMART CONTEXT BUILDER CODE (DISABLED) =====
        # 🔬 REASON FOR DISABLE: Over-compression (91.4%) caused:
        #    - Loss of PMC identifiers
        #    - Loss of specific study details
        #    - LLM hallucinations due to insufficient context
        #    - Original: 123k chars → Optimized: 10k chars (too aggressive)
        #
        # # Build evidence dict format for context builder
        # evidence_items_for_builder = []
        # for entry in all_evidence:
        #     evidence_items_for_builder.append({
        #         'filename': entry.get('source', 'Unknown'),
        #         'risk_level': entry.get('risk_level', 'UNKNOWN'),
        #         'risk_type': entry.get('risk_type', 'Unknown'),
        #         'quote': entry.get('quote', ''),
        #         'explanation': entry.get('explanation', ''),
        #         'paper_summary': entry.get('quote', '')
        #     })
        # 
        # # Initialize smart context builder
        # context_builder = create_smart_context_builder(max_chars=120000)
        # 
        # # Build optimized context
        # optimized_context, stats = context_builder.build_optimized_context(
        #     evidence_items=evidence_items_for_builder,
        #     forensic_items=forensic_data
        # )
        # 
        # # Log optimization results
        # logger.success(f"🧠 Context Optimization Complete:")
        # logger.info(f"   Original: {len(''.join(all_evidence_context))} chars")
        # logger.info(f"   Optimized: {stats['total_chars']} chars ({stats['total_tokens']} tokens)")
        # logger.info(f"   Compression: {stats['compression_ratio']:.1%}")
        # logger.info(f"   Critical Items: {stats['critical_count']}")
        # logger.info(f"   Medium Items: {stats['medium_count']}")
        # logger.info(f"   Clean Items: {stats['clean_count']}")
        
        # 🔥 ENHANCED: Validate evidence text quality
        MIN_PAYLOAD_SIZE = 30000  # Minimum 30k chars for quality analysis (increased from 1k)
        MIN_PMC_COUNT = 20  # Minimum 5 PMC citations expected
        
        # Check size
        if stats['total_chars'] < MIN_PAYLOAD_SIZE:
            logger.error(f"❌ CRITICAL: Evidence text too small ({stats['total_chars']:,} chars < {MIN_PAYLOAD_SIZE:,})")
            logger.error(f"❌ This will cause hallucinations in report generation!")
            logger.error(f"❌ Failed files: {len(failed_files)}, Successful: {success_count}")
            if success_count == 0:
                logger.error("❌ All PDFs failed - cannot generate report")
                return {
                    "error": "All PDF extractions failed",
                    "failed_files": failed_files,
                    "total_files": total_files,
                    "context_size": stats['total_chars']
                }
            else:
                logger.warning(f"⚠️ Continuing with limited data - report quality will be compromised")
        else:
            logger.success(f"✅ Evidence text size OK: {stats['total_chars']:,} chars")
        
        # Check PMC citations
        pmc_count = optimized_context.count('PMC')
        if pmc_count < MIN_PMC_COUNT:
            logger.warning(f"⚠️ LOW PMC CITATIONS: Only {pmc_count} found (expected >={MIN_PMC_COUNT})")
            logger.warning(f"⚠️ Report may lack specific references - investigate evidence formatting")
        else:
            logger.success(f"✅ PMC citations OK: {pmc_count} found")
        
        # Check evidence diversity
        if len(all_evidence) == 0:
            logger.error(f"❌ CRITICAL: No evidence items extracted!")
        elif len(all_evidence) < 10:
            logger.warning(f"⚠️ LOW EVIDENCE DIVERSITY: Only {len(all_evidence)} items")
        else:
            logger.success(f"✅ Evidence diversity OK: {len(all_evidence)} items")
        
        # 🔥 Validate minimum content threshold (legacy check - now redundant)
        MIN_PAYLOAD_SIZE_LEGACY = 1000  # Old threshold for backward compatibility
        if stats['total_chars'] < MIN_PAYLOAD_SIZE_LEGACY:
            logger.error(f"❌ CRITICAL: Evidence payload critically small ({stats['total_chars']} chars < {MIN_PAYLOAD_SIZE_LEGACY})")
            logger.error(f"❌ Failed files: {len(failed_files)}, Successful: {success_count}")
            if success_count == 0:
                logger.error("❌ All PDFs failed - cannot generate report")
                return {
                    "error": "All PDF extractions failed",
                    "failed_files": failed_files,
                    "total_files": total_files,
                    "context_size": stats['total_chars']
                }
        
        # 🔥 NEW: Validate query relevance (check if core keywords appear in evidence)
        user_query = state.get("user_query", "")
        core_keywords = user_query.lower().split()[:3]  # First 3 words are usually key concepts
        if core_keywords:
            keyword_found = any(kw in optimized_context.lower() for kw in core_keywords if len(kw) > 3)
            if not keyword_found:
                logger.warning(f"⚠️ RELEVANCE WARNING: Core keywords '{', '.join(core_keywords)}' not found in evidence")
                logger.warning(f"⚠️ This may indicate query drift or irrelevant results")
        
        return {
            "text_evidence": all_evidence,
            "compiled_evidence_text": optimized_context,  # 🧠 Use optimized context
            "failed_files": failed_files,
            "total_files": total_files,
            "pdf_files": state.get("pdf_paths", []),
            "context_stats": stats  # 🧠 Include optimization stats
        }
        
    except Exception as e:
        logger.error(f"❌ Evidence Miner failed: {e}")
        return {
            "text_evidence": [],
            "compiled_evidence_text": "",
            "failed_files": [],
            "total_files": 0,
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
            - forensic_failed_files: List of files that failed forensic audit
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
                "forensic_evidence": [],
                "forensic_failed_files": []
            }
        
        # 🚨 PHASE 2 FIX: Track forensic audit failures
        all_audit_results = []
        forensic_failed_files = []
        
        # 🔥 FIXED: Use configurable PDF limit instead of hardcoded [:3]
        max_pdfs = settings.MAX_PDFS_TO_PROCESS if settings.MAX_PDFS_TO_PROCESS > 0 else len(pdf_paths)
        total_forensic_files = min(max_pdfs, len(pdf_paths))
        total_available = len(pdf_paths)
        
        logger.info(f"📊 Forensic Audit Config: Processing {total_forensic_files} out of {total_available} available PDFs")
        
        # Audit all PDFs (up to configured limit)
        for i, pdf_path in enumerate(pdf_paths[:total_forensic_files], 1):
            logger.info(f"\n📄 Auditing PDF {i}/{total_forensic_files} (Total available: {total_available}): {pdf_path}")
            
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
                    logger.success(f"✅ Audited {len(audit_dicts)} images from PDF {i}")
                else:
                    # 🚨 PHASE 2 FIX: Track missing files
                    logger.error(f"❌ PDF not found locally: {pdf_path}")
                    forensic_failed_files.append(os.path.basename(pdf_path))
            
            except Exception as e:
                # 🚨 PHASE 2 FIX: Track forensic audit failures
                logger.error(f"❌ Failed to audit PDF {i}: {e}")
                forensic_failed_files.append(os.path.basename(pdf_path))
                continue
        
        success_count = total_forensic_files - len(forensic_failed_files)
        logger.success(f"✅ Audited {len(all_audit_results)} images from {success_count}/{total_forensic_files} PDFs")
        
        if forensic_failed_files:
            logger.warning(f"⚠️ Forensic audit failed for {len(forensic_failed_files)} files: {', '.join(forensic_failed_files)}")
        
        return {
            "forensic_evidence": all_audit_results,
            "forensic_failed_files": forensic_failed_files  # 🚨 NEW: Track forensic failures
        }
        
    except Exception as e:
        logger.error(f"❌ Forensic Auditor failed: {e}")
        return {
            "forensic_evidence": [],
            "forensic_failed_files": [],
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
    
    🚨 PHASE 2: Anti-Silent-Failure Logic
    Calculates risk_override based on failed files to prevent
    "toxic positivity" in reports when PDFs fail to process.
    
    Args:
        state: Current workflow state with text_evidence and forensic_evidence
    
    Returns:
        Updated state with validated data and risk_override
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
        
        # 🚨 PHASE 2: Calculate failure metrics
        failed_files = state.get("failed_files", [])
        forensic_failed = state.get("forensic_failed_files", [])
        
        # 📊 STEP 3: Use Global PDF Count
        total_files = len(state.get("pdf_files", []))  # Global count from harvester
        if total_files == 0:
            # Fallback to pdf_paths
            total_files = len(state.get("pdf_paths", []))
        if total_files == 0:
            # Last fallback: use total_files from miner
            total_files = state.get("total_files", 0)
        
        # Merge all failed files (deduplicate)
        all_failed_files = list(set(failed_files + forensic_failed))
        total_failed = len(all_failed_files)
        
        logger.info(f"\n🚨 Failure Analysis:")
        logger.info(f"   - Total PDFs Attempted: {total_files}")
        logger.info(f"   - Evidence Mining Failed: {len(failed_files)}")
        logger.info(f"   - Forensic Audit Failed: {len(forensic_failed)}")
        logger.info(f"   - Total Unique Failures: {total_failed}")
        
        # 🚨 PHASE 2: Implement Anti-Silent-Failure Logic
        risk_override = None
        analysis_status = "COMPLETE"
        
        if total_files == 0:
            logger.warning("⚠️ No PDFs were processed")
            risk_override = "UNKNOWN (NO DATA)"
            analysis_status = "NO_DATA"
        elif total_failed == total_files:
            logger.error("❌ CRITICAL: All PDFs failed to process!")
            risk_override = "UNKNOWN (CRITICAL DATA FAILURE)"
            analysis_status = "CRITICAL_FAILURE"
        elif total_failed > 0:
            failure_rate = (total_failed / total_files) * 100
            logger.warning(f"⚠️ PARTIAL SUCCESS: {total_failed}/{total_files} files failed ({failure_rate:.0f}%)")
            risk_override = f"UNCERTAIN (INCOMPLETE DATA - {failure_rate:.0f}% failed)"
            analysis_status = "PARTIAL_SUCCESS"
        else:
            logger.success("✅ All PDFs processed successfully")
            analysis_status = "COMPLETE"
        
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
        logger.info(f"   Analysis Status: {analysis_status}")
        if risk_override:
            logger.warning(f"   Risk Override: {risk_override}")
        
        return {
            "project_name": project_name,
            "status": "graph_complete",
            "analysis_status": analysis_status,  # 🚨 NEW: Track analysis completeness
            "risk_override": risk_override,  # 🚨 NEW: Override risk assessment if data missing
            "total_failed_files": total_failed,  # 🚨 NEW: Total failure count
            "all_failed_files": all_failed_files  # 🚨 NEW: Combined failure list
        }
        
    except Exception as e:
        logger.error(f"❌ Graph Builder failed: {e}")
        return {
            "errors": [f"GraphBuilder: {str(e)}"],
            "status": "graph_failed",
            "risk_override": "UNKNOWN (SYSTEM ERROR)"
        }


def writer_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 4: ReportWriter - Final Report Synthesis
    
    Synthesizes all evidence into a comprehensive biomedical due diligence report.
    
    🚨 PHASE 2: Passes failure metadata to enforce honest reporting
    🔥 NEW: Supports segmented generation mode (recommended)
    
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
        
        # 🚨 PHASE 2: Extract failure metadata for honest reporting
        compiled_evidence_text = state.get("compiled_evidence_text", "")
        
        # 📊 STEP 3: Fix Global Statistics Calculation
        # Get Global Count from State (total PDFs from harvester, not just processed batch)
        total_pdfs_global = len(state.get("pdf_files", []))  # Global list from harvester
        if total_pdfs_global == 0:
            # Fallback to pdf_paths if pdf_files not available
            total_pdfs_global = len(state.get("pdf_paths", []))
        if total_pdfs_global == 0:
            # Last fallback: use total_files from miner
            total_pdfs_global = state.get("total_files", 0)
        
        total_failed = state.get("total_failed_files", 0)
        risk_override = state.get("risk_override")
        analysis_status = state.get("analysis_status", "UNKNOWN")
        failed_files_list = state.get("all_failed_files", [])
        
        logger.info(f"\n🚨 Passing failure metadata to Report Writer:")
        logger.info(f"   - Analysis Status: {analysis_status}")
        logger.info(f"   - Total Files (GLOBAL): {total_pdfs_global}")  # 🔥 Clarify it's global
        logger.info(f"   - Failed Files: {total_failed}")
        if risk_override:
            logger.warning(f"   - Risk Override: {risk_override}")
        if failed_files_list:
            logger.warning(f"   - Failed: {', '.join(failed_files_list)}")
        
        # 📊 STEP 3: Update Writer Payload with Global Stats
        payload = {
            "user_query": state["user_query"],
            "harvest_data": harvest_data,
            "forensic_data": forensic_data,
            "evidence_data": evidence_data,
            "project_name": state.get("project_name"),
            "output_dir": "final_reports",
            # 🚨 PHASE 2: Pass failure metadata
            "compiled_evidence_text": compiled_evidence_text,
            "failed_count": total_failed,
            "total_files": total_pdfs_global,  # 🔥 Dynamic Global Count (not batch size)
            "risk_override": risk_override,
            "analysis_status": analysis_status,
            "failed_files": failed_files_list
        }
        
        print(f"\n🔥 DEBUG: Final Payload to Writer:")
        print(f"🔥 DEBUG: - evidence_context length: {len(compiled_evidence_text)}")
        print(f"🔥 DEBUG: - total_files (global): {total_pdfs_global}")
        print(f"🔥 DEBUG: - failed_count: {total_failed}")
        
        # 🔥 NEW: Try segmented generation first (recommended)
        logger.info("\n🔥 Attempting segmented generation mode...")
        use_segmented = True  # Can be configured via settings
        
        try:
            if use_segmented and hasattr(agent, 'write_report_segmented'):
                report_output = agent.write_report_segmented(**payload, use_segmented=True)
                logger.success("✅ Segmented generation succeeded")
            else:
                logger.info("Segmented mode not available, using traditional mode")
                report_output = agent.write_report(**payload)
        except Exception as seg_error:
            logger.warning(f"⚠️ Segmented generation failed: {seg_error}")
            logger.info("Falling back to traditional generation...")
            report_output = agent.write_report(**payload)
        
        logger.success(f"✅ Report generated successfully")
        logger.info(f"   Recommendation: {report_output.recommendation}")
        logger.info(f"   Risk Score: {report_output.risk_score:.1f}/10")
        
        # PHASE 3.1 FIX: Return markdown content AND file path for frontend injection
        return {
            "final_report": report_output.markdown_content,
            "final_report_path": report_output.markdown_path,  # NEW: Add file path
            "final_report_markdown": report_output.markdown_content,
            "recommendation": report_output.recommendation,
            "risk_score": report_output.risk_score,
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
