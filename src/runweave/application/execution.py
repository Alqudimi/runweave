from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from runweave.adapters.filesystem import LocalWorkspaceObserver
from runweave.adapters.sqlite_store import SQLiteStateStore
from runweave.adapters.subprocess_runner import LocalCommandRunner
from runweave.domain.enums import Decision, FailureKind, StepStatus
from runweave.domain.models import RepairPlan, Runbook, StepDefinition
from runweave.domain.validation import execution_plan, step_map
from runweave.errors import ConfirmationRequiredError, RepairPlanStaleError
from runweave.ports.interfaces import CommandContext

from .common import attempt_id, make_contract, run_id, runbook_digest


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    run_id: str
    status: StepStatus


def _now() -> datetime:
    return datetime.now(UTC)


def _environment(step: StepDefinition) -> dict[str, str]:
    return {name: os.environ[name] for name in step.env if name in os.environ}


def _execute_step(
    runbook: Runbook,
    run_id_value: str,
    step: StepDefinition,
    store: SQLiteStateStore,
) -> StepStatus:
    observer = LocalWorkspaceObserver()
    runner = LocalCommandRunner()
    contract_before = make_contract(runbook, step, observer)
    current_attempt = attempt_id()
    store.record_step_started(
        run_id_value,
        step.step_id,
        current_attempt,
        contract_before,
        _now(),
    )
    result = runner.run(
        CommandContext(
            tuple(step.command),
            (runbook.root / step.working_dir).resolve(),
            _environment(step),
            step.timeout_seconds,
        )
    )
    contract_after = make_contract(runbook, step, observer)
    missing_output = any(not item.exists for item in contract_after.output_fingerprints)
    if result.status is StepStatus.SUCCEEDED and missing_output:
        result = replace(
            result,
            status=StepStatus.FAILED,
            failure_kind=FailureKind.OUTPUT_VIOLATION,
            termination_reason="OUTPUT_VIOLATION",
            stderr=(result.stderr + "\n[runweave] declared output is missing\n").strip(),
        )
    store.record_step_finished(
        run_id_value,
        step.step_id,
        current_attempt,
        result,
        contract_after,
        _now(),
    )
    return result.status


def execute_runbook(
    runbook: Runbook,
    store: SQLiteStateStore | None = None,
) -> ExecutionOutcome:
    store = store or SQLiteStateStore(runbook.state_dir / "state.sqlite3")
    store.initialize()
    identifier = run_id()
    plan = execution_plan(runbook)
    store.create_run(identifier, runbook_digest(runbook), _now(), plan.order)
    steps = step_map(runbook)
    statuses = {step_id: StepStatus.PENDING for step_id in plan.order}

    for step_id in plan.order:
        step = steps[step_id]
        dependencies_ready = all(
            statuses[dependency] is StepStatus.SUCCEEDED for dependency in step.depends_on
        )
        if not dependencies_ready:
            statuses[step_id] = StepStatus.BLOCKED
            store.update_step_status(identifier, step_id, StepStatus.BLOCKED)
            continue
        statuses[step_id] = _execute_step(runbook, identifier, step, store)

    succeeded = all(status is StepStatus.SUCCEEDED for status in statuses.values())
    final_status = StepStatus.SUCCEEDED if succeeded else StepStatus.FAILED
    store.finish_run(identifier, final_status, _now())
    return ExecutionOutcome(identifier, final_status)


def resume_runbook(
    runbook: Runbook,
    run_id_value: str,
    repair_plan: RepairPlan,
    store: SQLiteStateStore | None = None,
    confirmed_side_effects: set[str] | None = None,
) -> ExecutionOutcome:
    store = store or SQLiteStateStore(runbook.state_dir / "state.sqlite3")
    store.initialize()
    run = store.load_run(run_id_value)
    current_digest = runbook_digest(runbook)
    plan_matches = (
        repair_plan.run_id == run_id_value
        and repair_plan.source_runbook_digest == current_digest
        and run.runbook_digest == current_digest
    )
    if not plan_matches:
        raise RepairPlanStaleError(
            "Repair plan is stale because the runbook definition or source run does not match.",
            {"run_id": run_id_value, "plan_id": repair_plan.plan_id},
        )
    confirmed = confirmed_side_effects or set()
    steps = step_map(runbook)
    decisions = {item.step_id: item for item in repair_plan.decisions}
    statuses = {step_id: StepStatus.SUCCEEDED for step_id in steps}
    for step_id in execution_plan(runbook).order:
        decision = decisions[step_id]
        step = steps[step_id]
        if decision.decision is Decision.REUSE:
            continue
        if decision.decision is Decision.BLOCK:
            statuses[step_id] = StepStatus.BLOCKED
            store.update_step_status(run_id_value, step_id, StepStatus.BLOCKED)
            continue
        if decision.requires_confirmation and step_id not in confirmed:
            raise ConfirmationRequiredError(
                f"Step '{step_id}' requires explicit confirmation before resume.",
                {
                    "run_id": run_id_value,
                    "plan_id": repair_plan.plan_id,
                    "step_id": step_id,
                },
            )
        dependencies_ready = all(
            statuses[dependency] is StepStatus.SUCCEEDED for dependency in step.depends_on
        )
        if not dependencies_ready:
            statuses[step_id] = StepStatus.BLOCKED
            store.update_step_status(run_id_value, step_id, StepStatus.BLOCKED)
            continue
        statuses[step_id] = _execute_step(runbook, run_id_value, step, store)
    succeeded = all(status is StepStatus.SUCCEEDED for status in statuses.values())
    final_status = StepStatus.SUCCEEDED if succeeded else StepStatus.FAILED
    store.finish_run(run_id_value, final_status, _now())
    return ExecutionOutcome(run_id_value, final_status)
