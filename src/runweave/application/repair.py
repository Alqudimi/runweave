from __future__ import annotations

import secrets
from datetime import UTC, datetime

from runweave.adapters.filesystem import LocalWorkspaceObserver
from runweave.adapters.sqlite_store import SQLiteStateStore
from runweave.domain.models import RepairDecision, RepairPlan, Runbook
from runweave.domain.recovery import (
    RecoveryContext,
    command_digest,
    evaluate_step,
    step_policy_digest,
)
from runweave.domain.validation import execution_plan, step_map

from .common import runbook_digest


def _plan_id() -> str:
    return f"plan_{secrets.token_hex(8)}"


def build_repair_plan(
    runbook: Runbook,
    run_id: str,
    store: SQLiteStateStore,
) -> RepairPlan:
    store.initialize()
    run = store.load_run(run_id)
    records = store.load_steps(run_id)
    observer = LocalWorkspaceObserver()
    steps = step_map(runbook)
    current_digest = runbook_digest(runbook)
    contexts: dict[str, RecoveryContext] = {}
    for step_id, step in steps.items():
        record = records[step_id]
        current_inputs = observer.fingerprint(runbook.root, step.inputs)
        current_outputs = observer.fingerprint(runbook.root, step.outputs)
        stored_contract = record.contract
        command_matches = (
            stored_contract is not None and stored_contract.command_digest == command_digest(step)
        )
        policy_matches = (
            stored_contract is not None
            and stored_contract.policy_digest == step_policy_digest(step)
        )
        inputs_match = (
            stored_contract is not None and stored_contract.input_fingerprints == current_inputs
        )
        contexts[step_id] = RecoveryContext(
            runbook_digest_matches=current_digest == run.runbook_digest,
            command_digest_matches=command_matches,
            policy_digest_matches=policy_matches,
            inputs_match=inputs_match,
            outputs_valid=all(item.exists for item in current_outputs),
            dependency_decisions={},
        )

    decisions: dict[str, RepairDecision] = {}
    for step_id in execution_plan(runbook).order:
        step = steps[step_id]
        context = contexts[step_id]
        context = RecoveryContext(
            context.runbook_digest_matches,
            context.command_digest_matches,
            context.policy_digest_matches,
            context.inputs_match,
            context.outputs_valid,
            decisions,
        )
        decisions[step_id] = evaluate_step(
            runbook,
            step,
            records[step_id],
            context,
        )

    plan = RepairPlan(
        _plan_id(),
        run_id,
        current_digest,
        tuple(decisions[step.step_id] for step in runbook.steps),
        datetime.now(UTC),
    )
    store.save_repair_plan(plan)
    return plan
