from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from runweave.errors import RunbookValidationError

from .canonical import digest
from .models import Runbook, StepDefinition

_STEP_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    order: tuple[str, ...]
    levels: tuple[tuple[str, ...], ...]
    digest: str


def _path_is_safe(root: Path, path: str) -> bool:
    candidate = (root / path).resolve(strict=False)
    return candidate == root or root in candidate.parents


def validate_runbook(runbook: Runbook) -> None:
    if runbook.schema_version != 1:
        raise RunbookValidationError(
            "UNSUPPORTED_SCHEMA_VERSION",
            f"Unsupported runbook schema version: {runbook.schema_version}.",
            {"schema_version": runbook.schema_version},
        )
    if not runbook.name.strip():
        raise RunbookValidationError("INVALID_RUNBOOK_NAME", "Runbook name must not be empty.")
    if not runbook.steps:
        raise RunbookValidationError("NO_STEPS", "Runbook must contain at least one step.")

    ids = [step.step_id for step in runbook.steps]
    if len(ids) != len(set(ids)):
        raise RunbookValidationError("DUPLICATE_STEP_ID", "Step IDs must be unique.")
    known = set(ids)
    for step in runbook.steps:
        if not _STEP_ID.fullmatch(step.step_id):
            raise RunbookValidationError(
                "INVALID_STEP_ID",
                f"Step ID '{step.step_id}' does not match the required format.",
                {"step_id": step.step_id},
            )
        unknown = sorted(set(step.depends_on) - known)
        if unknown:
            raise RunbookValidationError(
                "UNKNOWN_DEPENDENCY",
                f"Step '{step.step_id}' depends on unknown steps: {', '.join(unknown)}.",
                {"step_id": step.step_id, "unknown": unknown},
            )
        declared_paths = (*step.inputs, *step.outputs, step.working_dir)
        unsafe = [path for path in declared_paths if not _path_is_safe(runbook.root, path)]
        if unsafe:
            raise RunbookValidationError(
                "PATH_OUTSIDE_ROOT",
                f"Step '{step.step_id}' declares paths outside the workspace root.",
                {"step_id": step.step_id, "paths": unsafe},
            )
        if len(set(step.env)) != len(step.env):
            raise RunbookValidationError(
                "DUPLICATE_ENV_NAME",
                f"Step '{step.step_id}' declares the same environment name more than once.",
            )
    execution_plan(runbook)


def execution_plan(runbook: Runbook) -> ExecutionPlan:
    steps = {step.step_id: step for step in runbook.steps}
    indegree = {step_id: len(step.depends_on) for step_id, step in steps.items()}
    dependents: dict[str, list[str]] = {step_id: [] for step_id in steps}
    for step in runbook.steps:
        for dependency in step.depends_on:
            dependents[dependency].append(step.step_id)

    current = sorted(step_id for step_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    levels: list[tuple[str, ...]] = []
    while current:
        level = tuple(current)
        levels.append(level)
        order.extend(current)
        next_ids: list[str] = []
        for step_id in current:
            for dependent in dependents[step_id]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    next_ids.append(dependent)
        current = sorted(next_ids)

    if len(order) != len(steps):
        unresolved = sorted(set(steps) - set(order))
        raise RunbookValidationError(
            "DEPENDENCY_CYCLE",
            "Runbook contains a dependency cycle.",
            {"steps": unresolved},
        )
    return ExecutionPlan(tuple(order), tuple(levels), digest({"order": order, "levels": levels}))


def step_map(runbook: Runbook) -> dict[str, StepDefinition]:
    return {step.step_id: step for step in runbook.steps}
