from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .enums import (
    Decision,
    EvidenceMode,
    FailureKind,
    ReasonCode,
    RetryMode,
    SideEffect,
    StepStatus,
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    mode: RetryMode = RetryMode.NEVER
    max_attempts: int = 1
    retryable_errors: frozenset[FailureKind] = frozenset()

    def __post_init__(self) -> None:
        if self.mode is RetryMode.NEVER and self.max_attempts != 1:
            raise ValueError("NEVER retry policy must have max_attempts=1")
        if self.mode is RetryMode.ONCE and self.max_attempts != 2:
            raise ValueError("ONCE retry policy must have max_attempts=2")
        if self.mode is RetryMode.BOUNDED and not 2 <= self.max_attempts <= 10:
            raise ValueError("BOUNDED retry policy must allow between 2 and 10 attempts")

    def allows(self, kind: FailureKind, attempts_so_far: int) -> bool:
        return (
            kind in self.retryable_errors
            and attempts_so_far < self.max_attempts
            and self.mode is not RetryMode.NEVER
        )


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    require_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class StepDefinition:
    step_id: str
    command: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    working_dir: str = "."
    env: tuple[str, ...] = ()
    timeout_seconds: float = 3600.0
    side_effect: SideEffect = SideEffect.PURE
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    evidence: EvidenceMode = EvidenceMode.STANDARD
    recovery: RecoveryPolicy = field(default_factory=RecoveryPolicy)

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("step_id must not be empty")
        if not self.command or any(not value for value in self.command):
            raise ValueError("command must be a non-empty argv vector")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class Runbook:
    schema_version: int
    name: str
    source_path: Path
    root: Path
    state_dir: Path
    steps: tuple[StepDefinition, ...]


@dataclass(frozen=True, slots=True)
class PathFingerprint:
    path: str
    kind: str
    digest: str | None
    size: int | None
    mtime_ns: int | None
    exists: bool


@dataclass(frozen=True, slots=True)
class StepContract:
    command_digest: str
    policy_digest: str
    input_fingerprints: tuple[PathFingerprint, ...]
    output_fingerprints: tuple[PathFingerprint, ...]


@dataclass(frozen=True, slots=True)
class AttemptResult:
    status: StepStatus
    exit_code: int | None
    failure_kind: FailureKind | None
    stdout: str
    stderr: str
    duration_ms: int
    termination_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    runbook_digest: str
    status: StepStatus
    started_at: datetime
    finished_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StepRecord:
    run_id: str
    step_id: str
    status: StepStatus
    contract: StepContract | None
    attempt_count: int = 0
    failure_kind: FailureKind | None = None
    exit_code: int | None = None
    last_attempt_id: str | None = None


@dataclass(frozen=True, slots=True)
class RepairDecision:
    step_id: str
    decision: Decision
    reason_code: ReasonCode
    explanation: str
    requires_confirmation: bool = False
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepairPlan:
    plan_id: str
    run_id: str
    source_runbook_digest: str
    decisions: tuple[RepairDecision, ...]
    created_at: datetime

    @property
    def requires_confirmation(self) -> bool:
        return any(item.requires_confirmation for item in self.decisions)


def as_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, tuple | frozenset):
        return [as_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): as_jsonable(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {key: as_jsonable(getattr(value, key)) for key in value.__dataclass_fields__}
    return value
