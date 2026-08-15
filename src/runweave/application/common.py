from __future__ import annotations

import secrets

from runweave.domain.canonical import digest
from runweave.domain.models import Runbook, StepContract, StepDefinition
from runweave.domain.recovery import command_digest, step_policy_digest
from runweave.ports.interfaces import WorkspaceObserver


def run_id() -> str:
    return f"run_{secrets.token_hex(8)}"


def attempt_id() -> str:
    return f"attempt_{secrets.token_hex(8)}"


def plan_id() -> str:
    return f"plan_{secrets.token_hex(8)}"


def runbook_digest(runbook: Runbook) -> str:
    return digest(
        {
            "schema_version": runbook.schema_version,
            "name": runbook.name,
            "steps": runbook.steps,
        }
    )


def make_contract(
    runbook: Runbook,
    step: StepDefinition,
    observer: WorkspaceObserver,
) -> StepContract:
    inputs = observer.fingerprint(runbook.root, step.inputs)
    outputs = observer.fingerprint(runbook.root, step.outputs)
    return StepContract(command_digest(step), step_policy_digest(step), inputs, outputs)
