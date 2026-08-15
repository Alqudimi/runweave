from __future__ import annotations

from pathlib import Path

from runweave.adapters.sqlite_store import SQLiteStateStore
from runweave.adapters.yaml_runbook import load_runbook
from runweave.application.execution import execute_runbook, resume_runbook
from runweave.application.repair import build_repair_plan
from runweave.domain.enums import Decision, StepStatus


def runbook_text(command: str) -> str:
    return f"""schema_version: 1
name: direct
root: .
state_dir: .runweave
steps:
  - id: write
    command: [python, -c, '{command}']
    outputs: [out.txt]
    side_effect: WORKSPACE_WRITE
"""


def test_direct_execution_persists_state_and_repair_reuses_success(tmp_path: Path) -> None:
    path = tmp_path / "runweave.yml"
    path.write_text(
        runbook_text('from pathlib import Path; Path("out.txt").write_text("ok")'),
        encoding="utf-8",
    )
    runbook = load_runbook(path)
    store = SQLiteStateStore(runbook.state_dir / "state.sqlite3")
    outcome = execute_runbook(runbook, store)
    assert outcome.status is StepStatus.SUCCEEDED
    assert store.load_run(outcome.run_id).status is StepStatus.SUCCEEDED
    plan = build_repair_plan(runbook, outcome.run_id, store)
    assert plan.decisions[0].decision is Decision.REUSE


def test_direct_resume_retries_a_failed_step(tmp_path: Path) -> None:
    path = tmp_path / "runweave.yml"
    path.write_text(
        runbook_text(
            "from pathlib import Path; import sys; "
            'p=Path("attempts.txt"); '
            "n=int(p.read_text()) if p.exists() else 0; "
            "p.write_text(str(n+1)); "
            'sys.exit(1) if n == 0 else Path("out.txt").write_text("ok")'
        ),
        encoding="utf-8",
    )
    runbook = load_runbook(path)
    store = SQLiteStateStore(runbook.state_dir / "state.sqlite3")
    failed = execute_runbook(runbook, store)
    assert failed.status is StepStatus.FAILED
    plan = build_repair_plan(runbook, failed.run_id, store)
    assert plan.decisions[0].decision is Decision.RERUN
    resumed = resume_runbook(runbook, failed.run_id, plan, store)
    assert resumed.status is StepStatus.SUCCEEDED
    assert store.load_steps(failed.run_id)["write"].attempt_count == 2
