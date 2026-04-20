"""Workflow execution facade.

Provides a stable service API for graph execution, streaming updates, and
progress callback wiring without exposing graph internals to app layers.
"""

from typing import Any, Dict, Generator, Optional, Tuple

from src.agents.supervisor import (
    get_workflow_state,
    resume_workflow,
    run_cassandra_workflow,
    stream_cassandra_workflow,
)


class WorkflowService:
    """Anti-corruption service for running Cassandra workflow pipelines."""

    def run(
        self,
        user_query: str,
        pdf_paths: Optional[list] = None,
        checkpointer: Any = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return run_cassandra_workflow(
            user_query=user_query,
            pdf_paths=pdf_paths,
            checkpointer=checkpointer,
            thread_id=thread_id,
        )

    def stream(
        self,
        user_query: str,
        pdf_paths: Optional[list] = None,
        progress_callback: Any = None,
        checkpointer: Any = None,
        thread_id: Optional[str] = None,
        interrupt_before: Optional[list] = None,
        allow_interrupts: bool = False,
    ) -> Generator[Tuple[str, Dict[str, Any]], None, None]:
        yield from stream_cassandra_workflow(
            user_query=user_query,
            pdf_paths=pdf_paths,
            progress_callback=progress_callback,
            checkpointer=checkpointer,
            thread_id=thread_id,
            interrupt_before=interrupt_before,
            allow_interrupts=allow_interrupts,
        )

    def get_state(self, thread_id: str, checkpointer: Any = None) -> Any:
        return get_workflow_state(thread_id=thread_id, checkpointer=checkpointer)

    def resume(
        self,
        thread_id: str,
        checkpointer: Any,
        progress_callback: Any = None,
    ) -> Generator[Tuple[str, Dict[str, Any]], None, None]:
        yield from resume_workflow(
            thread_id=thread_id,
            checkpointer=checkpointer,
            progress_callback=progress_callback,
        )


__all__ = ["WorkflowService"]
