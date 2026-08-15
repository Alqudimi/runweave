from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "runweave", "--json", *args],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )


def test_retryable_failure_can_be_repaired_and_resumed(tmp_path: Path) -> None:
    runbook = tmp_path / "runweave.yml"
    first = json.dumps(
        [
            "python",
            "-c",
            "from pathlib import Path; import sys; "
            "p=Path('counter.txt'); "
            "n=int(p.read_text()) if p.exists() else 0; "
            "p.write_text(str(n+1)); "
            "sys.exit(1) if n == 0 else None",
        ]
    )
    second = json.dumps(
        [
            "python",
            "-c",
            "from pathlib import Path; assert Path('counter.txt').read_text() == '2'",
        ]
    )
    runbook.write_text(
        f"""schema_version: 1
name: recovery
root: .
state_dir: .runweave
steps:
  - id: retryable
    command: {first}
    outputs: [counter.txt]
    side_effect: WORKSPACE_WRITE
    retry:
      mode: ONCE
      retryable_errors: [NON_ZERO_EXIT]
  - id: dependent
    command: {second}
    depends_on: [retryable]
    inputs: [counter.txt]
    side_effect: PURE
""",
        encoding="utf-8",
    )
    failed = cli(tmp_path, "run", str(runbook))
    assert failed.returncode == 4, failed.stderr
    run_id = json.loads(failed.stdout)["data"]["run_id"]

    repaired = cli(tmp_path, "repair", run_id, "--runbook", str(runbook))
    assert repaired.returncode == 0, repaired.stderr
    repair_payload = json.loads(repaired.stdout)
    plan_id = repair_payload["data"]["plan_id"]
    decisions = {item["step_id"]: item["decision"] for item in repair_payload["data"]["decisions"]}
    assert decisions["retryable"] == "RETRY"
    assert decisions["dependent"] == "RERUN"

    resumed = cli(tmp_path, "resume", run_id, "--runbook", str(runbook), "--plan", plan_id)
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout)["data"]["status"] == "SUCCEEDED"

    final_plan = cli(tmp_path, "repair", run_id, "--runbook", str(runbook))
    assert final_plan.returncode == 0
    final_decisions = {
        item["step_id"]: item["decision"]
        for item in json.loads(final_plan.stdout)["data"]["decisions"]
    }
    assert final_decisions["retryable"] == "REUSE"
    assert final_decisions["dependent"] == "REUSE"


def test_external_write_requires_confirmation_before_resume(tmp_path: Path) -> None:
    runbook = tmp_path / "runweave.yml"
    command = json.dumps(["python", "-c", "raise SystemExit(9)"])
    runbook.write_text(
        f"""schema_version: 1
name: external
root: .
state_dir: .runweave
steps:
  - id: publish
    command: {command}
    side_effect: EXTERNAL_WRITE
""",
        encoding="utf-8",
    )
    failed = cli(tmp_path, "run", str(runbook))
    assert failed.returncode == 4
    run_id = json.loads(failed.stdout)["data"]["run_id"]
    repair = cli(tmp_path, "repair", run_id, "--runbook", str(runbook))
    payload = json.loads(repair.stdout)
    plan_id = payload["data"]["plan_id"]
    assert payload["data"]["decisions"][0]["decision"] == "CONFIRM"

    blocked = cli(
        tmp_path,
        "resume",
        run_id,
        "--runbook",
        str(runbook),
        "--plan",
        plan_id,
    )
    assert blocked.returncode == 3
    assert "SIDE_EFFECT_CONFIRMATION_REQUIRED" in blocked.stdout


def test_stale_repair_plan_is_rejected(tmp_path: Path) -> None:
    runbook = tmp_path / "runweave.yml"
    runbook.write_text(
        """schema_version: 1
name: stale
root: .
state_dir: .runweave
steps:
  - id: write
    command: [python, -c, 'from pathlib import Path; Path(\"out.txt\").write_text(\"ok\")']
    outputs: [out.txt]
    side_effect: WORKSPACE_WRITE
""",
        encoding="utf-8",
    )
    completed = cli(tmp_path, "run", str(runbook))
    run_id = json.loads(completed.stdout)["data"]["run_id"]
    repair = cli(tmp_path, "repair", run_id, "--runbook", str(runbook))
    plan_id = json.loads(repair.stdout)["data"]["plan_id"]
    changed = runbook.read_text(encoding="utf-8").replace("name: stale", "name: changed")
    runbook.write_text(changed, encoding="utf-8")
    stale = cli(
        tmp_path,
        "resume",
        run_id,
        "--runbook",
        str(runbook),
        "--plan",
        plan_id,
    )
    assert stale.returncode == 3
    assert "PLAN_STALE" in stale.stdout
