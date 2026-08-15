from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

import yaml

from runweave.domain.enums import EvidenceMode, FailureKind, RetryMode, SideEffect
from runweave.domain.models import RecoveryPolicy, RetryPolicy, Runbook, StepDefinition
from runweave.domain.validation import validate_runbook
from runweave.errors import RunbookValidationError

_EnumT = TypeVar("_EnumT", bound=StrEnum)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RunbookValidationError("INVALID_FIELD_TYPE", f"Field '{field}' must be a mapping.")
    return value


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    valid = isinstance(value, list) and all(isinstance(item, str) and bool(item) for item in value)
    if not valid:
        raise RunbookValidationError(
            "INVALID_FIELD_TYPE",
            f"Field '{field}' must be a list of non-empty strings.",
        )
    return tuple(value)


def _enum(enum_type: type[_EnumT], value: Any, field: str) -> _EnumT:
    try:
        return enum_type(str(value).upper())
    except (ValueError, TypeError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise RunbookValidationError(
            "INVALID_ENUM",
            f"Field '{field}' must be one of: {allowed}.",
        ) from exc


def _retry(raw: Any, step_id: str) -> RetryPolicy:
    data = _mapping(raw or {}, f"steps[{step_id}].retry")
    mode = _enum(RetryMode, data.get("mode", "NEVER"), "retry.mode")
    default_attempts = {RetryMode.NEVER: 1, RetryMode.ONCE: 2}.get(mode, 3)
    max_attempts = data.get("max_attempts", default_attempts)
    if not isinstance(max_attempts, int):
        raise RunbookValidationError(
            "INVALID_FIELD_TYPE",
            f"Step '{step_id}' retry.max_attempts must be an integer.",
        )
    errors = frozenset(
        _enum(FailureKind, item, "retry.retryable_errors")
        for item in _strings(data.get("retryable_errors"), "retry.retryable_errors")
    )
    try:
        return RetryPolicy(mode, max_attempts, errors)
    except ValueError as exc:
        raise RunbookValidationError(
            "INVALID_RETRY_POLICY",
            f"Step '{step_id}' has an invalid retry policy.",
        ) from exc


def _step(raw: Any) -> StepDefinition:
    data = _mapping(raw, "step")
    step_id = data.get("id")
    command = data.get("command")
    if not isinstance(step_id, str) or not step_id:
        raise RunbookValidationError(
            "MISSING_STEP_ID",
            "Each step requires a non-empty string id.",
        )
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) for item in command)
    ):
        raise RunbookValidationError(
            "INVALID_COMMAND",
            f"Step '{step_id}' command must be a non-empty list of strings.",
        )
    recovery = _mapping(data.get("recovery") or {}, f"steps[{step_id}].recovery")
    require_confirmation = recovery.get("require_confirmation", False)
    if not isinstance(require_confirmation, bool):
        raise RunbookValidationError(
            "INVALID_FIELD_TYPE",
            f"Step '{step_id}' recovery.require_confirmation must be boolean.",
        )
    timeout = data.get("timeout_seconds", 3600.0)
    valid_timeout = isinstance(timeout, int | float) and not isinstance(timeout, bool)
    if not valid_timeout:
        raise RunbookValidationError(
            "INVALID_FIELD_TYPE",
            f"Step '{step_id}' timeout_seconds must be numeric.",
        )
    return StepDefinition(
        step_id=step_id,
        command=tuple(command),
        depends_on=_strings(data.get("depends_on"), f"steps[{step_id}].depends_on"),
        inputs=_strings(data.get("inputs"), f"steps[{step_id}].inputs"),
        outputs=_strings(data.get("outputs"), f"steps[{step_id}].outputs"),
        working_dir=str(data.get("working_dir", ".")),
        env=_strings(data.get("env"), f"steps[{step_id}].env"),
        timeout_seconds=float(timeout),
        side_effect=_enum(SideEffect, data.get("side_effect", "PURE"), "side_effect"),
        retry=_retry(data.get("retry"), step_id),
        evidence=_enum(EvidenceMode, data.get("evidence", "STANDARD"), "evidence"),
        recovery=RecoveryPolicy(require_confirmation),
    )


def load_runbook(path: Path) -> Runbook:
    path = path.resolve()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RunbookValidationError(
            "RUNBOOK_READ_ERROR",
            f"Could not read runbook: {path}",
        ) from exc
    data = _mapping(raw, "runbook")
    allowed = {"schema_version", "name", "root", "state_dir", "steps"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise RunbookValidationError(
            "UNKNOWN_FIELD",
            f"Unknown runbook fields: {', '.join(unknown)}",
        )
    schema_version = data.get("schema_version")
    name = data.get("name")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise RunbookValidationError(
            "INVALID_SCHEMA_VERSION",
            "schema_version must be an integer.",
        )
    if not isinstance(name, str):
        raise RunbookValidationError("MISSING_RUNBOOK_NAME", "name must be a string.")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        raise RunbookValidationError("INVALID_STEPS", "steps must be a list.")
    root = (path.parent / str(data.get("root", "."))).resolve()
    state_dir = (root / str(data.get("state_dir", ".runweave"))).resolve()
    runbook = Runbook(
        schema_version,
        name,
        path,
        root,
        state_dir,
        tuple(_step(item) for item in raw_steps),
    )
    validate_runbook(runbook)
    return runbook
