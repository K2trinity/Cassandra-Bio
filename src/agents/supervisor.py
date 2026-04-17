"""Cassandra Supervisor - harvest/report workflow orchestration.

This module is intentionally slim:
- Graph topology is defined in src.graph.workflow
- Node implementations live in src.graph.nodes
- Supervisor provides execution wrappers for app/service compatibility
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Dict, List, Optional, Tuple


def _resolve_logger():
    """Resolve loguru logger when available, else use stdlib logging."""
    try:
        return importlib.import_module("loguru").logger
    except Exception:  # pragma: no cover - dependency fallback for lightweight environments
        return logging.getLogger(__name__)


logger = _resolve_logger()

from src.graph.contracts import CONTRACT_VERSION
from src.graph.state import AgentState


def _build_biomedical_profile(state: AgentState) -> Dict[str, Any]:
    """Backward-compatible export for existing dev checks/tests."""
    from src.graph.profile import build_biomedical_profile

    return build_biomedical_profile(state)


def create_cassandra_workflow() -> Any:
    """Create the LangGraph topology for Cassandra."""
    from src.graph.workflow import create_workflow

    logger.info("Building Cassandra workflow topology")
    return create_workflow()


def _normalize_interrupt_nodes(interrupt_before) -> List[str]:
    """Normalize user-supplied interrupt_before values into a clean node list."""
    if not interrupt_before:
        return []

    raw_nodes = interrupt_before
    if isinstance(raw_nodes, str):
        raw_nodes = [raw_nodes]

    normalized: List[str] = []
    for node in raw_nodes:
        node_name = str(node or "").strip()
        if node_name:
            normalized.append(node_name)
    return normalized


def compile_workflow(checkpointer=None, interrupt_before=None, allow_interrupts: bool = False):
    """Compile workflow with optional checkpointer and interrupt settings."""
    workflow = create_cassandra_workflow()

    requested_interrupt_nodes = _normalize_interrupt_nodes(interrupt_before)
    if requested_interrupt_nodes:
        logger.warning(
            "Interrupt nodes were requested but Cassandra now enforces "
            "uninterrupted execution; ignoring interrupt_before."
        )

    compile_kwargs = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer

    app = workflow.compile(**compile_kwargs)

    if checkpointer:
        logger.info(
            "Workflow compiled with checkpointer "
            "(interrupt_before=None, uninterrupted mode)"
        )
    else:
        logger.info("Workflow compiled successfully (no checkpointer)")

    return app


def _initial_state(user_query: str, pdf_paths: Optional[List[str]] = None) -> AgentState:
    """Build initial workflow state for the 6-node analysis pipeline.

    Topology: harvester → extension_handoff → evidence_synthesizer
              → clinical_analyzer → quality_assessor → writer
    """
    return {
        "user_query": user_query,
        "pdf_paths": pdf_paths or [],
        "harvested_data": [],
        "harvest_data_layers": {},
        "harvest_source_payloads": {},
        "harvest_frontend_payload": {},
        "extension_payloads": {},
        "dataflow_contract_version": CONTRACT_VERSION,
        "final_report": None,
        "final_report_path": None,
        "final_report_markdown": None,
        "project_name": None,
        "assessment_override": None,
        "analysis_status": "INITIALIZED",
        "status": "initialized",
        "analysis_focus": "HARVEST_AND_REPORT_ONLY",
        "biomedical_profile": None,
        "disease_areas": [],
        "drug_baselines": [],
        "target_signals": [],
        "company_entities": [],
        "clinical_data": {},
        "evidence_stats": {},
        "errors": [],
    }


def run_cassandra_workflow(
    user_query: str,
    pdf_paths: list = None,
    checkpointer=None,
    thread_id: str = None,
) -> Dict[str, Any]:
    """Execute workflow end-to-end and return final state."""
    logger.info("Cassandra workflow (sync) initiated")

    app = compile_workflow(checkpointer=checkpointer)
    initial_state = _initial_state(user_query=user_query, pdf_paths=pdf_paths)

    run_config = {"configurable": {"thread_id": thread_id}} if thread_id else None

    try:
        final_state = app.invoke(initial_state, config=run_config)
        logger.info(
            "Workflow complete: "
            f"status={final_state.get('status')}, harvested={len(final_state.get('harvested_data', []))}, "
            f"report={'yes' if final_state.get('final_report') else 'no'}"
        )
        return final_state
    except Exception as exc:
        logger.error(f"Workflow execution failed: {exc}")
        raise


def stream_cassandra_workflow(
    user_query: str,
    pdf_paths: list = None,
    progress_callback=None,
    checkpointer=None,
    thread_id: str = None,
    interrupt_before: list = None,
    allow_interrupts: bool = False,
):
    """Execute workflow in stream mode and yield (node_name, state)."""
    logger.info("Cassandra workflow (stream) initiated")

    app = compile_workflow(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        allow_interrupts=allow_interrupts,
    )

    initial_state = _initial_state(user_query=user_query, pdf_paths=pdf_paths)
    run_config = {"configurable": {"thread_id": thread_id}} if thread_id else None

    full_state = dict(initial_state)
    stream_input = initial_state
    resume_attempts = 0
    max_resume_attempts = 8

    try:
        while True:
            saw_interrupt = False

            for event in app.stream(stream_input, config=run_config, stream_mode="updates"):
                for node_name, partial_state in event.items():
                    if node_name == "__interrupt__":
                        saw_interrupt = True
                        logger.warning("Interrupt event received during stream; attempting auto-resume.")
                        continue

                    if isinstance(partial_state, dict):
                        for key, value in partial_state.items():
                            if isinstance(value, list) and isinstance(full_state.get(key), list):
                                full_state[key] = full_state[key] + value
                            else:
                                full_state[key] = value

                    if progress_callback:
                        progress_callback(node_name, full_state)
                    yield node_name, full_state

            if not saw_interrupt:
                break

            if not checkpointer or not thread_id:
                logger.warning(
                    "Interrupt occurred without checkpointer/thread_id; cannot resume from checkpoint."
                )
                break

            resume_attempts += 1
            if resume_attempts > max_resume_attempts:
                raise RuntimeError("Exceeded automatic resume attempts after repeated interrupts")

            stream_input = None
    except Exception as exc:
        logger.error(f"Streaming workflow failed: {exc}")
        raise


def get_workflow_state(thread_id: str, checkpointer=None):
    """Get current workflow state from checkpointer-backed execution."""
    if not checkpointer:
        return None
    app = compile_workflow(checkpointer=checkpointer, allow_interrupts=False)
    config = {"configurable": {"thread_id": thread_id}}
    return app.get_state(config)


def resume_workflow(thread_id: str, checkpointer, progress_callback=None):
    """Resume a paused workflow from checkpointer state."""
    logger.info(f"Resuming workflow for thread {thread_id}")
    app = compile_workflow(checkpointer=checkpointer, allow_interrupts=False)
    config = {"configurable": {"thread_id": thread_id}}

    full_state = app.get_state(config).values
    stream_input = None
    resume_attempts = 0
    max_resume_attempts = 8

    try:
        while True:
            saw_interrupt = False
            for event in app.stream(stream_input, config=config, stream_mode="updates"):
                for node_name, partial_state in event.items():
                    if node_name == "__interrupt__":
                        saw_interrupt = True
                        logger.warning("Interrupt event received during resume; retrying auto-resume.")
                        continue

                    if isinstance(partial_state, dict):
                        for key, value in partial_state.items():
                            if isinstance(value, list) and isinstance(full_state.get(key), list):
                                full_state[key] = full_state[key] + value
                            else:
                                full_state[key] = value

                    if progress_callback:
                        progress_callback(node_name, full_state)
                    yield node_name, full_state

            if not saw_interrupt:
                break

            resume_attempts += 1
            if resume_attempts > max_resume_attempts:
                raise RuntimeError("Exceeded automatic resume attempts in resume_workflow")

            stream_input = None
    except Exception as exc:
        logger.error(f"Resumed streaming failed: {exc}")
        raise


if __name__ == "__main__":
    result = run_cassandra_workflow("Analyze diabetes treatment landscape")
    print(result.get("status"))
