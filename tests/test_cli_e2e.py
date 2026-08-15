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


def write_runbook(path: Path, command: str) -> None:
    argv = json.dumps(["python", "-c", command])
    path.write_text(
        f"""schema_version: 1
name: e2e
root: .
state_dir: .runweave
steps:
  - id: run
    command: {argv}
    outputs: [out.txt]
    side_effect: WORKSPACE_WRITE
""",
        encoding="utf-8",
    )


def test_cli_init_validate_plan_and_run(tmp_path: Path) -> None:
    initialized = cli(tmp_path, "init", "generated.yml")
    assert initialized.returncode == 0
    assert (tmp_path / "generated.yml").exists()
    assert cli(tmp_path, "validate", "generated.yml").returncode == 0
    assert cli(tmp_path, "plan", "generated.yml").returncode == 0
    result = cli(tmp_path, "run", "generated.yml")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    status = cli(tmp_path, "status", payload["data"]["run_id"], "--runbook", "generated.yml")
    assert status.returncode == 0
    assert status.stdout


def test_failed_step_returns_failure_and_persists_state(tmp_path: Path) -> None:
    runbook = tmp_path / "runweave.yml"
    write_runbook(
        runbook,
        "from pathlib import Path; Path('out.txt').write_text('bad'); raise SystemExit(4)",
    )
    result = cli(tmp_path, "run", str(runbook))
    assert result.returncode == 4
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    status = cli(tmp_path, "status", payload["data"]["run_id"], "--runbook", str(runbook))
    assert status.returncode == 0
    assert "FAILED" in status.stdout
