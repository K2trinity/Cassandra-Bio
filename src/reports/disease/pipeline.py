from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any


StageState = tuple[str, dict[str, Any]]
StageRunner = Callable[[dict[str, Any]], StageState | None]
StageCondition = Callable[[dict[str, Any]], bool]


@dataclass(frozen=True)
class PipelineStage:
    """A small DAG-like pipeline stage with explicit dependencies."""

    stage_id: str
    run: StageRunner
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    condition: StageCondition | None = None


class DAGPipeline:
    """Execute dependency-ordered stages over a shared pipeline context."""

    def __init__(self, stages: list[PipelineStage]) -> None:
        self._stages = list(stages)
        self._ordered = self._topological_order(self._stages)

    def run(self, context: dict[str, Any]) -> Iterator[StageState]:
        completed: set[str] = set()
        for stage in self._ordered:
            if stage.condition is not None and not stage.condition(context):
                completed.add(stage.stage_id)
                continue
            missing = [dep for dep in stage.depends_on if dep not in completed]
            if missing:
                joined = ", ".join(missing)
                raise ValueError(f"Stage {stage.stage_id} missing dependencies: {joined}")
            output = stage.run(context)
            completed.add(stage.stage_id)
            if output is not None:
                yield output

    @staticmethod
    def _topological_order(stages: list[PipelineStage]) -> list[PipelineStage]:
        by_id: dict[str, PipelineStage] = {}
        for stage in stages:
            if stage.stage_id in by_id:
                raise ValueError(f"Duplicate pipeline stage: {stage.stage_id}")
            by_id[stage.stage_id] = stage

        for stage in stages:
            for dep in stage.depends_on:
                if dep not in by_id:
                    raise ValueError(f"Stage {stage.stage_id} depends on unknown stage: {dep}")

        ordered: list[PipelineStage] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(stage_id: str) -> None:
            if stage_id in visited:
                return
            if stage_id in visiting:
                raise ValueError(f"Pipeline stage dependency cycle at: {stage_id}")
            visiting.add(stage_id)
            stage = by_id[stage_id]
            for dep in stage.depends_on:
                visit(dep)
            visiting.remove(stage_id)
            visited.add(stage_id)
            ordered.append(stage)

        for stage in stages:
            visit(stage.stage_id)
        return ordered


__all__ = ["DAGPipeline", "PipelineStage"]
