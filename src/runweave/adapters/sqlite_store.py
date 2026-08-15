from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from runweave.domain.enums import Decision, FailureKind, ReasonCode, StepStatus
from runweave.domain.models import (
    AttemptResult,
    PathFingerprint,
    RepairDecision,
    RepairPlan,
    RunRecord,
    StepContract,
    StepRecord,
    as_jsonable,
)
from runweave.ports.interfaces import StateStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (schema_version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    runbook_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS steps (
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    status TEXT NOT NULL,
    contract_json TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    failure_kind TEXT,
    exit_code INTEGER,
    last_attempt_id TEXT,
    PRIMARY KEY (run_id, step_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    exit_code INTEGER,
    failure_kind TEXT,
    stdout TEXT NOT NULL,
    stderr TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    termination_reason TEXT,
    contract_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transitions (
    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step_id TEXT,
    from_state TEXT,
    to_state TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS repair_plans (
    plan_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_runbook_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decisions_json TEXT NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _contract_json(contract: StepContract) -> str:
    return json.dumps(as_jsonable(contract), sort_keys=True)


def _contract(value: str | None) -> StepContract | None:
    if value is None:
        return None
    raw = json.loads(value)
    return StepContract(
        raw["command_digest"],
        raw["policy_digest"],
        tuple(PathFingerprint(**item) for item in raw["input_fingerprints"]),
        tuple(PathFingerprint(**item) for item in raw["output_fingerprints"]),
    )


def _insert_transition(
    connection: sqlite3.Connection,
    run_id: str,
    to_state: str,
    occurred_at: datetime,
    reason: str,
    step_id: str | None = None,
    from_state: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO transitions(run_id, step_id, from_state, to_state, occurred_at, reason)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (run_id, step_id, from_state, to_state, _iso(occurred_at), reason),
    )


class SQLiteStateStore(StateStore):
    def __init__(self, database: Path) -> None:
        self.database = database

    def _connection(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(_SCHEMA)
            row = connection.execute("SELECT schema_version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_meta(schema_version) VALUES (1)")
            elif row[0] != 1:
                raise RuntimeError(f"Unsupported state schema: {row[0]}")

    def create_run(
        self,
        run_id: str,
        runbook_digest: str,
        started_at: datetime,
        step_ids: tuple[str, ...],
    ) -> None:
        self.initialize()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, NULL)",
                (run_id, runbook_digest, StepStatus.RUNNING.value, _iso(started_at)),
            )
            connection.executemany(
                "INSERT INTO steps(run_id, step_id, status) VALUES (?, ?, ?)",
                [(run_id, step_id, StepStatus.PENDING.value) for step_id in step_ids],
            )
            _insert_transition(
                connection,
                run_id,
                StepStatus.RUNNING.value,
                started_at,
                "RUN_CREATED",
            )

    def load_run(self, run_id: str) -> RunRecord:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown run: {run_id}")
        return RunRecord(
            run_id,
            row["runbook_digest"],
            StepStatus(row["status"]),
            _dt(row["started_at"]),
            _dt(row["finished_at"]) if row["finished_at"] else None,
        )

    def load_steps(self, run_id: str) -> dict[str, StepRecord]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM steps WHERE run_id = ? ORDER BY step_id", (run_id,)
            ).fetchall()
        return {
            row["step_id"]: StepRecord(
                run_id,
                row["step_id"],
                StepStatus(row["status"]),
                _contract(row["contract_json"]),
                row["attempt_count"],
                FailureKind(row["failure_kind"]) if row["failure_kind"] else None,
                row["exit_code"],
                row["last_attempt_id"],
            )
            for row in rows
        }

    def record_step_started(
        self,
        run_id: str,
        step_id: str,
        attempt_id: str,
        contract: StepContract,
        started_at: datetime,
    ) -> None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status, attempt_count FROM steps WHERE run_id = ? AND step_id = ?",
                (run_id, step_id),
            ).fetchone()
            if row is None:
                raise KeyError(step_id)
            attempt_no = int(row["attempt_count"]) + 1
            connection.execute(
                "UPDATE steps SET status = ?, attempt_count = ?, contract_json = ?, "
                "last_attempt_id = ? WHERE run_id = ? AND step_id = ?",
                (
                    StepStatus.RUNNING.value,
                    attempt_no,
                    _contract_json(contract),
                    attempt_id,
                    run_id,
                    step_id,
                ),
            )
            connection.execute(
                "INSERT INTO attempts VALUES "
                "(?, ?, ?, ?, ?, ?, NULL, NULL, NULL, '', '', 0, NULL, ?)",
                (
                    attempt_id,
                    run_id,
                    step_id,
                    attempt_no,
                    StepStatus.RUNNING.value,
                    _iso(started_at),
                    _contract_json(contract),
                ),
            )
            _insert_transition(
                connection,
                run_id,
                StepStatus.RUNNING.value,
                started_at,
                "ATTEMPT_STARTED",
                step_id,
                row["status"],
            )

    def record_step_finished(
        self,
        run_id: str,
        step_id: str,
        attempt_id: str,
        result: AttemptResult,
        contract: StepContract,
        finished_at: datetime,
    ) -> None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status FROM steps WHERE run_id = ? AND step_id = ?",
                (run_id, step_id),
            ).fetchone()
            if row is None:
                raise KeyError(step_id)
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, exit_code = ?, "
                "failure_kind = ?, stdout = ?, stderr = ?, duration_ms = ?, "
                "termination_reason = ?, contract_json = ? WHERE attempt_id = ?",
                (
                    result.status.value,
                    _iso(finished_at),
                    result.exit_code,
                    result.failure_kind.value if result.failure_kind else None,
                    result.stdout,
                    result.stderr,
                    result.duration_ms,
                    result.termination_reason,
                    _contract_json(contract),
                    attempt_id,
                ),
            )
            connection.execute(
                "UPDATE steps SET status = ?, failure_kind = ?, exit_code = ?, "
                "contract_json = ? WHERE run_id = ? AND step_id = ?",
                (
                    result.status.value,
                    result.failure_kind.value if result.failure_kind else None,
                    result.exit_code,
                    _contract_json(contract),
                    run_id,
                    step_id,
                ),
            )
            _insert_transition(
                connection,
                run_id,
                result.status.value,
                finished_at,
                result.termination_reason or "ATTEMPT_FINISHED",
                step_id,
                row["status"],
            )

    def save_repair_plan(self, plan: RepairPlan) -> None:
        with self._connection() as connection:
            decisions = [as_jsonable(item) for item in plan.decisions]
            connection.execute(
                "INSERT OR REPLACE INTO repair_plans VALUES (?, ?, ?, ?, ?)",
                (
                    plan.plan_id,
                    plan.run_id,
                    plan.source_runbook_digest,
                    _iso(plan.created_at),
                    json.dumps(decisions, sort_keys=True),
                ),
            )

    def load_repair_plan(self, plan_id: str) -> RepairPlan:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM repair_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown repair plan: {plan_id}")
        decisions = tuple(
            RepairDecision(
                item["step_id"],
                Decision(item["decision"]),
                ReasonCode(item["reason_code"]),
                item["explanation"],
                item["requires_confirmation"],
                tuple(item["depends_on"]),
            )
            for item in json.loads(row["decisions_json"])
        )
        return RepairPlan(
            row["plan_id"],
            row["run_id"],
            row["source_runbook_digest"],
            decisions,
            _dt(row["created_at"]),
        )

    def update_step_status(self, run_id: str, step_id: str, status: StepStatus) -> None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status FROM steps WHERE run_id = ? AND step_id = ?",
                (run_id, step_id),
            ).fetchone()
            if row is None:
                raise KeyError(step_id)
            connection.execute(
                "UPDATE steps SET status = ? WHERE run_id = ? AND step_id = ?",
                (status.value, run_id, step_id),
            )
            _insert_transition(
                connection,
                run_id,
                status.value,
                _now(),
                "DEPENDENCY_STATE",
                step_id,
                row["status"],
            )

    def finish_run(self, run_id: str, status: StepStatus, finished_at: datetime) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ?",
                (status.value, _iso(finished_at), run_id),
            )
            _insert_transition(
                connection,
                run_id,
                status.value,
                finished_at,
                "RUN_FINISHED",
            )
