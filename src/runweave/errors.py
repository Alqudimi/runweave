from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ExitCode:
    OK = 0
    INVALID_INPUT = 2
    BLOCKED_OR_UNSAFE = 3
    STEP_FAILURE = 4
    INTERNAL = 5


@dataclass(frozen=True, slots=True)
class RunWeaveError(Exception):
    code: str
    message: str
    details: dict[str, Any] | None = None
    exit_code: int = ExitCode.INVALID_INPUT
    suggested_action: str | None = None

    def __str__(self) -> str:
        return self.message


class RunbookValidationError(RunWeaveError):
    pass


class StateConflictError(RunWeaveError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("STATE_CONFLICT", message, details, ExitCode.BLOCKED_OR_UNSAFE)


class RepairPlanStaleError(RunWeaveError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("PLAN_STALE", message, details, ExitCode.BLOCKED_OR_UNSAFE)


class ConfirmationRequiredError(RunWeaveError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            "SIDE_EFFECT_CONFIRMATION_REQUIRED",
            message,
            details,
            ExitCode.BLOCKED_OR_UNSAFE,
        )
