from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from runweave.domain.enums import StepStatus
from runweave.domain.models import (
    AttemptResult,
    PathFingerprint,
    RepairPlan,
    RunRecord,
    StepContract,
    StepRecord,
)


@dataclass(frozen=True, slots=True)
class CommandContext:
    argv: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]
    timeout_seconds: float


class CommandRunner(Protocol):
    def run(self, context: CommandContext) -> AttemptResult: ...


class WorkspaceObserver(Protocol):
    def fingerprint(
        self,
        root: Path,
        paths: tuple[str, ...],
    ) -> tuple[PathFingerprint, ...]: ...


class StateStore(Protocol):
    def initialize(self) -> None: ...

    def create_run(
        self,
        run_id: str,
        runbook_digest: str,
        started_at: datetime,
        step_ids: tuple[str, ...],
    ) -> None: ...

    def load_run(self, run_id: str) -> RunRecord: ...

    def load_steps(self, run_id: str) -> dict[str, StepRecord]: ...

    def record_step_started(
        self,
        run_id: str,
        step_id: str,
        attempt_id: str,
        contract: StepContract,
        started_at: datetime,
    ) -> None: ...

    def record_step_finished(
        self,
        run_id: str,
        step_id: str,
        attempt_id: str,
        result: AttemptResult,
        contract: StepContract,
        finished_at: datetime,
    ) -> None: ...

    def save_repair_plan(self, plan: RepairPlan) -> None: ...

    def load_repair_plan(self, plan_id: str) -> RepairPlan: ...

    def update_step_status(
        self,
        run_id: str,
        step_id: str,
        status: StepStatus,
    ) -> None: ...

    def finish_run(
        self,
        run_id: str,
        status: StepStatus,
        finished_at: datetime,
    ) -> None: ...


class EvidenceExporter(Protocol):
    def export(self, run: RunRecord, steps: dict[str, StepRecord]) -> str: ...
