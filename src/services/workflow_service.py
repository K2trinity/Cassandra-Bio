"""Workflow execution facade for the disease report pipeline."""

import inspect
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Optional, Tuple

from src.reports.disease.orchestrator import DiseaseReportOrchestrator


class WorkflowService:
    """Anti-corruption service for running Cassandra disease report pipelines."""

    def __init__(
        self,
        orchestrator_factory: Callable[[], Any] | None = None,
        output_dir: str | Path = "final_reports",
    ) -> None:
        self.orchestrator_factory = orchestrator_factory or DiseaseReportOrchestrator
        self.output_dir = Path(output_dir)

    @staticmethod
    def _supports_target_mode(method: Callable[..., Any]) -> bool:
        parameters = inspect.signature(method).parameters
        return (
            "analysis_target_type" in parameters
            or any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
        )

    def run(
        self,
        user_query: str,
        pdf_paths: Optional[list] = None,
        checkpointer: Any = None,
        thread_id: Optional[str] = None,
        narrative_language: str = "zh",
        analysis_target_type: str = "auto",
    ) -> Dict[str, Any]:
        _ = (pdf_paths, checkpointer, thread_id)
        orchestrator = self.orchestrator_factory()
        run_kwargs = {
            "user_query": user_query,
            "output_dir": str(self.output_dir),
            "narrative_language": narrative_language,
        }
        if self._supports_target_mode(orchestrator.run):
            run_kwargs["analysis_target_type"] = analysis_target_type
        return orchestrator.run(**run_kwargs)

    def stream(
        self,
        user_query: str,
        pdf_paths: Optional[list] = None,
        progress_callback: Any = None,
        checkpointer: Any = None,
        thread_id: Optional[str] = None,
        interrupt_before: Optional[list] = None,
        allow_interrupts: bool = False,
        narrative_language: str = "zh",
        analysis_target_type: str = "auto",
    ) -> Generator[Tuple[str, Dict[str, Any]], None, None]:
        _ = (pdf_paths, checkpointer, thread_id, interrupt_before, allow_interrupts)
        orchestrator = self.orchestrator_factory()
        stream_kwargs = {
            "user_query": user_query,
            "output_dir": str(self.output_dir),
            "narrative_language": narrative_language,
        }
        if self._supports_target_mode(orchestrator.stream):
            stream_kwargs["analysis_target_type"] = analysis_target_type
        for node_name, state in orchestrator.stream(**stream_kwargs):
            if progress_callback is not None:
                progress_callback(node_name, state)
            yield node_name, state

    def get_state(self, thread_id: str, checkpointer: Any = None) -> Any:
        _ = (thread_id, checkpointer)
        return None

    def resume(
        self,
        thread_id: str,
        checkpointer: Any,
        progress_callback: Any = None,
    ) -> Generator[Tuple[str, Dict[str, Any]], None, None]:
        _ = (thread_id, checkpointer, progress_callback)
        yield from ()


__all__ = ["WorkflowService"]
