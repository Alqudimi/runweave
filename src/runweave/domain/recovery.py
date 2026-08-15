from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest
from .enums import Decision, FailureKind, ReasonCode, SideEffect, StepStatus
from .models import RepairDecision, Runbook, StepContract, StepDefinition, StepRecord


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    runbook_digest_matches: bool
    command_digest_matches: bool
    policy_digest_matches: bool
    inputs_match: bool
    outputs_valid: bool
    dependency_decisions: dict[str, RepairDecision]


def step_policy_digest(step: StepDefinition) -> str:
    return digest(
        {
            "side_effect": step.side_effect,
            "retry": step.retry,
            "evidence": step.evidence,
            "recovery": step.recovery,
        }
    )


def command_digest(step: StepDefinition) -> str:
    return digest({"command": step.command, "working_dir": step.working_dir})


def contract_digest(step: StepDefinition, contract: StepContract) -> str:
    return digest(
        {
            "command_digest": command_digest(step),
            "policy_digest": step_policy_digest(step),
            "inputs": contract.input_fingerprints,
            "outputs": contract.output_fingerprints,
        }
    )


def _requires_confirmation(step: StepDefinition) -> bool:
    return step.recovery.require_confirmation or step.side_effect in {
        SideEffect.EXTERNAL_WRITE,
        SideEffect.DESTRUCTIVE,
    }


def evaluate_step(
    runbook: Runbook,
    step: StepDefinition,
    record: StepRecord,
    context: RecoveryContext,
) -> RepairDecision:
    dependency_decisions = context.dependency_decisions
    if any(
        dependency_decisions[dependency].decision in {Decision.BLOCK, Decision.CONFIRM}
        for dependency in step.depends_on
        if dependency in dependency_decisions
    ):
        return RepairDecision(
            step.step_id,
            Decision.BLOCK,
            ReasonCode.DEPENDENCY_INVALIDATED,
            "A dependency is not currently safe to reuse or execute.",
            False,
            step.depends_on,
        )
    if any(
        dependency_decisions[dependency].decision in {Decision.RERUN, Decision.RETRY}
        for dependency in step.depends_on
        if dependency in dependency_decisions
    ):
        return RepairDecision(
            step.step_id,
            Decision.RERUN,
            ReasonCode.DEPENDENCY_INVALIDATED,
            "A dependency will be rerun, so this dependent step must be rerun too.",
            _requires_confirmation(step),
            step.depends_on,
        )
    if record.status is StepStatus.SUCCEEDED:
        if not context.runbook_digest_matches:
            reason = ReasonCode.RUNBOOK_CHANGED
            text = "The runbook digest changed since this step succeeded."
        elif not context.command_digest_matches:
            reason = ReasonCode.COMMAND_CHANGED
            text = "The command or working directory changed since this step succeeded."
        elif not context.policy_digest_matches:
            reason = ReasonCode.POLICY_CHANGED
            text = "The step safety or retry policy changed since this step succeeded."
        elif not context.inputs_match:
            reason = ReasonCode.INPUT_CHANGED
            text = "A declared input fingerprint changed since this step succeeded."
        elif not context.outputs_valid:
            reason = ReasonCode.OUTPUT_MISSING
            text = "A declared output is missing or invalid."
        else:
            return RepairDecision(
                step.step_id,
                Decision.REUSE,
                ReasonCode.SUCCESS_CONTRACT_MATCH,
                "The previous success and all declared contract observations still match.",
                False,
                step.depends_on,
            )
        decision = Decision.CONFIRM if _requires_confirmation(step) else Decision.RERUN
        return RepairDecision(
            step.step_id,
            decision,
            reason,
            text,
            _requires_confirmation(step),
            step.depends_on,
        )

    failure_kind = record.failure_kind or FailureKind.INTERNAL
    retryable = step.retry.allows(failure_kind, record.attempt_count)
    if retryable:
        confirmation = _requires_confirmation(step)
        return RepairDecision(
            step.step_id,
            Decision.CONFIRM if confirmation else Decision.RETRY,
            ReasonCode.SIDE_EFFECT_CONFIRMATION if confirmation else ReasonCode.FAILURE_RETRYABLE,
            (
                "The failure class is allowed by policy, but side effects require confirmation."
                if confirmation
                else "The recorded failure class is retryable under the step policy."
            ),
            confirmation,
            step.depends_on,
        )
    confirmation = _requires_confirmation(step)
    return RepairDecision(
        step.step_id,
        Decision.CONFIRM if confirmation else Decision.RERUN,
        ReasonCode.SIDE_EFFECT_CONFIRMATION if confirmation else ReasonCode.FAILURE_NOT_RETRYABLE,
        (
            "The failed step requires explicit confirmation before another attempt."
            if confirmation
            else "The failed step will be rerun explicitly because automatic retry is not allowed."
        ),
        confirmation,
        step.depends_on,
    )


def evaluate_repair(
    runbook: Runbook,
    records: dict[str, StepRecord],
    contexts: dict[str, RecoveryContext],
) -> tuple[RepairDecision, ...]:
    return tuple(
        evaluate_step(runbook, step, records[step.step_id], contexts[step.step_id])
        for step in runbook.steps
    )
