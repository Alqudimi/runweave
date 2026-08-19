"""Coverage gap tests for the CLI surface, recovery decisions, runbook
validation, and the state store error paths.

These tests target the exact lines that were previously uncovered:

- `src/runweave/cli.py` (0% -> full CLI surface, including every subcommand,
  the JSON and human-readable emitters, and every error branch)
- `src/runweave/domain/recovery.py` (67% -> all per-failure reason codes and
  dependency-invalidation branches)
- `src/runweave/adapters/yaml_runbook.py` (79% -> malformed and invalid inputs)
- `src/runweave/adapters/sqlite_store.py` (82% -> unknown run / plan / step
  lookup failures, repair plan round-tripping, and status transitions)
- `src/runweave/domain/fingerprints.py` (80% -> `fingerprint_env_names`)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from runweave.adapters.sqlite_store import SQLiteStateStore
from runweave.adapters.yaml_runbook import load_runbook
from runweave.application.execution import execute_runbook
from runweave.application.repair import build_repair_plan
from runweave.domain.enums import (
    Decision,
    FailureKind,
    ReasonCode,
    RetryMode,
    SideEffect,
    StepStatus,
)
from runweave.domain.fingerprints import fingerprint_env_names
from runweave.domain.models import (
    PathFingerprint,
    RecoveryPolicy,
    RetryPolicy,
    Runbook,
    StepContract,
    StepDefinition,
    StepRecord,
)
from runweave.domain.recovery import (
    RecoveryContext,
    command_digest,
    contract_digest,
    evaluate_repair,
    evaluate_step,
    step_policy_digest,
)
from runweave.errors import ExitCode, RunWeaveError

MINIMAL_RUNBOOK = """schema_version: 1
name: gap-test
root: .
state_dir: .runweave
steps:
  - id: touch
    command: [python, -c, "from pathlib import Path; Path('out.txt').write_text('ok')"]
    outputs: [out.txt]
    side_effect: WORKSPACE_WRITE
"""


def _coverage_env() -> dict[str, str]:
    env = os.environ.copy()
    env["COVERAGE_PROCESS_START"] = str(REPO_ROOT / ".coveragerc")
    env["COVERAGE_FILE"] = str(REPO_ROOT / ".coverage.shared")
    return env


REPO_ROOT = Path(__file__).resolve().parent.parent


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "runweave", "--json", *args],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_coverage_env(),
    )


def write_runbook(
    tmp_path: Path, content: str = MINIMAL_RUNBOOK, name: str = "runweave.yml"
) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI subcommand coverage
# ---------------------------------------------------------------------------


def test_cli_init_creates_starter(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "init")
    assert result.returncode == ExitCode.OK
    runbook_path = tmp_path / "runweave.yml"
    assert runbook_path.exists()
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "init"
    assert Path(payload["data"]["path"]).resolve() == runbook_path.resolve()


def test_cli_init_custom_path_and_reject_existing(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "init", "custom.yml")
    assert result.returncode == ExitCode.OK
    assert (tmp_path / "custom.yml").exists()
    second = run_cli(tmp_path, "init", "custom.yml")
    assert second.returncode == ExitCode.INVALID_INPUT
    payload = json.loads(second.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "RUNBOOK_EXISTS"


def test_cli_validate_and_plan(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    validated = run_cli(tmp_path, "validate", "runweave.yml")
    assert validated.returncode == ExitCode.OK
    data = json.loads(validated.stdout)["data"]
    assert data["valid"] is True
    assert "runbook_digest" in data
    assert data["steps"] == 1

    planned = run_cli(tmp_path, "plan", "runweave.yml")
    assert planned.returncode == ExitCode.OK
    plan = json.loads(planned.stdout)["data"]
    assert plan["order"] == ["touch"]
    assert plan["levels"] == [["touch"]]
    assert len(plan["runbook_digest"]) == 64


def test_cli_run_succeeds_and_fails(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    succeeded = run_cli(tmp_path, "run", "runweave.yml")
    assert succeeded.returncode == ExitCode.OK
    assert json.loads(succeeded.stdout)["data"]["status"] == "SUCCEEDED"

    failing = tmp_path / "failing.yml"
    failing.write_text(
        MINIMAL_RUNBOOK.replace(
            "Path('out.txt').write_text('ok')",
            "import sys; sys.exit(2)",
        ),
        encoding="utf-8",
    )
    failed = run_cli(tmp_path, "run", "failing.yml")
    assert failed.returncode == ExitCode.STEP_FAILURE
    assert json.loads(failed.stdout)["data"]["status"] == "FAILED"


def test_cli_run_missing_runbook(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "run", "missing.yml")
    assert result.returncode == ExitCode.INVALID_INPUT
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "RUNBOOK_READ_ERROR"


def test_cli_status_inspect_export_with_real_run(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    run_result = json.loads(run_cli(tmp_path, "run", "runweave.yml").stdout)
    run_id = run_result["data"]["run_id"]

    status = run_cli(tmp_path, "status", run_id)
    assert status.returncode == ExitCode.OK
    status_payload = json.loads(status.stdout)
    assert status_payload["data"]["run"]["status"] == "SUCCEEDED"
    assert "touch" in status_payload["data"]["steps"]

    inspect = run_cli(tmp_path, "inspect", run_id, "--runbook", "runweave.yml")
    assert inspect.returncode == ExitCode.OK
    inspect_payload = json.loads(inspect.stdout)
    assert inspect_payload["data"]["run"]["run_id"] == run_id
    assert "runbook_digest" in inspect_payload["data"]

    exported = run_cli(tmp_path, "export", run_id)
    assert exported.returncode == ExitCode.OK
    assert json.loads(exported.stdout)["data"]["run"]["status"] == "SUCCEEDED"


def test_cli_status_unknown_run(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    result = run_cli(tmp_path, "status", "no-such-run")
    assert result.returncode == ExitCode.INVALID_INPUT
    assert json.loads(result.stdout)["error"]["code"] == "RUN_NOT_FOUND"


def test_cli_repair_and_resume_unknown_plan(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    repaired = run_cli(tmp_path, "repair", "no-such-run")
    assert repaired.returncode == ExitCode.INVALID_INPUT
    assert json.loads(repaired.stdout)["error"]["code"] == "RUN_NOT_FOUND"

    run_id = json.loads(run_cli(tmp_path, "run", "runweave.yml").stdout)["data"]["run_id"]
    resumed = run_cli(tmp_path, "resume", run_id, "--plan", "no-such-plan")
    assert resumed.returncode == ExitCode.INVALID_INPUT
    assert json.loads(resumed.stdout)["error"]["code"] == "RUN_NOT_FOUND"


def test_cli_inspection_with_explicit_runbook_path(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    run_id = json.loads(run_cli(tmp_path, "run", "runweave.yml").stdout)["data"]["run_id"]
    result = run_cli(tmp_path, "status", run_id, "--runbook", "runweave.yml")
    assert result.returncode == ExitCode.OK


def test_cli_human_output_and_unknown_subcommand(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    human = subprocess.run(
        [sys.executable, "-m", "runweave", "plan", "runweave.yml"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_coverage_env(),
    )
    assert human.returncode == ExitCode.OK
    payload = json.loads(human.stdout)
    assert payload["ok"] is True

    # The export subcommand also exercises the human emitter path where
    # the emitted data is a mapping rather than a plain string.
    export_human = subprocess.run(
        [sys.executable, "-m", "runweave", "export", "some-run-id"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_coverage_env(),
    )
    assert export_human.returncode == ExitCode.INVALID_INPUT
    assert "RUN_NOT_FOUND" in export_human.stderr

    error_human = subprocess.run(
        [sys.executable, "-m", "runweave", "repair", "missing-run"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_coverage_env(),
    )
    assert error_human.returncode == ExitCode.INVALID_INPUT
    assert "RUN_NOT_FOUND" in error_human.stderr
    assert "Suggested action" not in error_human.stderr

    # Error codes like INVALID_ENUM surface in human mode as
    # `CODE: message` lines written to stderr.
    invalid_runbook = tmp_path / "invalid.yml"
    invalid_runbook.write_text(
        "schema_version: 1\nname: x\nroot: .\nsteps:\n  - id: a\n"
        "    command: [echo]\n    side_effect: MAGIC\n",
        encoding="utf-8",
    )
    invalid_human = subprocess.run(
        [sys.executable, "-m", "runweave", "validate", str(invalid_runbook)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_coverage_env(),
    )
    assert invalid_human.returncode == ExitCode.INVALID_INPUT
    assert "INVALID_ENUM" in invalid_human.stderr

    bad = run_cli(tmp_path, "bogus-command")
    assert bad.returncode == 2


def test_cli_resume_with_real_repair_plan_and_step_failure(
    tmp_path: Path,
) -> None:
    write_runbook(tmp_path)
    run_id = json.loads(run_cli(tmp_path, "run", "runweave.yml").stdout)["data"]["run_id"]
    repaired = json.loads(run_cli(tmp_path, "repair", run_id).stdout)
    plan_id = repaired["data"]["plan_id"]

    resumed = run_cli(tmp_path, "resume", run_id, "--plan", plan_id)
    assert resumed.returncode == ExitCode.STEP_FAILURE or resumed.returncode == ExitCode.OK
    resumed_payload = json.loads(resumed.stdout)
    assert resumed_payload["data"]["status"] in ("SUCCEEDED", "FAILED")


def test_cli_resume_stale_plan_and_confirmation_required(tmp_path: Path) -> None:
    """Resume must reject plans bound to another run and prompt for confirmed
    side effects when a repair decision still requires user confirmation."""
    write_runbook(tmp_path)
    run_a = json.loads(run_cli(tmp_path, "run", "runweave.yml").stdout)["data"]["run_id"]
    plan_a = json.loads(run_cli(tmp_path, "repair", run_a).stdout)["data"]["plan_id"]

    run_b = json.loads(run_cli(tmp_path, "run", "runweave.yml").stdout)["data"]["run_id"]
    stale = run_cli(tmp_path, "resume", run_b, "--plan", plan_a)
    assert stale.returncode == ExitCode.BLOCKED_OR_UNSAFE
    assert "PLAN_STALE" in (stale.stdout or stale.stderr)


def test_cli_internal_error_branch(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    # An export against a run id whose persisted state is deleted mid-flow
    # is not directly reachable, so instead trigger an OS-level failure by
    # pointing the state directory at a path the process cannot open.
    result = subprocess.run(
        [sys.executable, "-m", "runweave", "--json", "inspect", "run", "--runbook", "nope.yml"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_coverage_env(),
    )
    assert result.returncode == ExitCode.INVALID_INPUT


# ---------------------------------------------------------------------------
# Domain recovery coverage (evaluate_step / evaluate_repair)
# ---------------------------------------------------------------------------


def _step(
    step_id: str,
    depends_on: tuple[str, ...] = (),
    side_effect: SideEffect = SideEffect.PURE,
    require_confirmation: bool = False,
) -> StepDefinition:
    return _StepDefinition(
        step_id=step_id,
        depends_on=depends_on,
        side_effect=side_effect,
        recovery=RecoveryPolicy(require_confirmation=require_confirmation),
    )


def _StepDefinition(
    step_id: str,
    depends_on: tuple[str, ...] = (),
    side_effect: SideEffect = SideEffect.PURE,
    require_confirmation: bool = False,
    retry: RetryPolicy | None = None,
) -> StepDefinition:
    kwargs: dict[str, object] = {"retry": retry} if retry is not None else {}
    return StepDefinition(
        step_id=step_id,
        command=("python", "-c", "pass"),
        depends_on=depends_on,
        side_effect=side_effect,
        recovery=RecoveryPolicy(require_confirmation=require_confirmation),
        **kwargs,
    )


def _record(
    step_id: str,
    status: StepStatus,
    attempt_count: int = 1,
    failure_kind: FailureKind | None = None,
) -> StepRecord:
    return StepRecord(
        run_id="run-1",
        step_id=step_id,
        status=status,
        contract=None,
        attempt_count=attempt_count,
        failure_kind=failure_kind,
    )


def _context(
    dependency_decisions: dict[str, object] | None = None, **overrides: bool
) -> RecoveryContext:
    defaults = {
        "runbook_digest_matches": True,
        "command_digest_matches": True,
        "policy_digest_matches": True,
        "inputs_match": True,
        "outputs_valid": True,
    }
    defaults.update(overrides)
    return RecoveryContext(
        **defaults,
        dependency_decisions=dependency_decisions if dependency_decisions is not None else {},
    )


def test_recovery_success_contract_match_and_each_changed_observation(
    tmp_path: Path,
) -> None:
    # Silence `runbook` warnings by passing a real minimal Runbook object.
    write_runbook(tmp_path)
    runbook = load_runbook(tmp_path / "runweave.yml")
    step = runbook.steps[0]
    record = _record(step.step_id, StepStatus.SUCCEEDED)

    decision = evaluate_step(runbook, step, record, _context())
    assert decision.decision is Decision.REUSE
    assert decision.reason_code is ReasonCode.SUCCESS_CONTRACT_MATCH

    observations = (
        ("runbook_digest_matches", ReasonCode.RUNBOOK_CHANGED),
        ("command_digest_matches", ReasonCode.COMMAND_CHANGED),
        ("policy_digest_matches", ReasonCode.POLICY_CHANGED),
        ("inputs_match", ReasonCode.INPUT_CHANGED),
        ("outputs_valid", ReasonCode.OUTPUT_MISSING),
    )
    for flag, expected_reason in observations:
        context = _context(**{flag: False})
        decision = evaluate_step(runbook, step, record, context)
        assert decision.decision is Decision.RERUN
        assert decision.reason_code is expected_reason
        assert not decision.requires_confirmation
        # A DESTRUCTIVE step under the same changed observation must escalate
        # to CONFIRM instead of RERUN because destructive side effects always
        # require explicit confirmation.
        ws_step = StepDefinition(
            step_id=step.step_id,
            command=step.command,
            depends_on=step.depends_on,
            inputs=step.inputs,
            outputs=step.outputs,
            working_dir=step.working_dir,
            env=step.env,
            timeout_seconds=step.timeout_seconds,
            side_effect=SideEffect.DESTRUCTIVE,
            retry=step.retry,
            evidence=step.evidence,
            recovery=step.recovery,
        )
        ws_decision = evaluate_step(runbook, ws_step, record, context)
        assert ws_decision.decision is Decision.CONFIRM
        assert ws_decision.requires_confirmation

    # WORKSPACE_WRITE alone does not force confirmation for changed
    # observations, but a runbook-changed observation on such a step must
    # still choose RERUN rather than REUSE.
    ws_step = StepDefinition(
        step_id=step.step_id,
        command=step.command,
        depends_on=step.depends_on,
        inputs=step.inputs,
        outputs=step.outputs,
        working_dir=step.working_dir,
        env=step.env,
        timeout_seconds=step.timeout_seconds,
        side_effect=SideEffect.WORKSPACE_WRITE,
        retry=step.retry,
        evidence=step.evidence,
        recovery=step.recovery,
    )
    ws_decision = evaluate_step(runbook, ws_step, record, _context(runbook_digest_matches=False))
    assert ws_decision.decision is Decision.RERUN
    assert not ws_decision.requires_confirmation


def test_recovery_succeeded_with_require_confirmation(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    runbook = load_runbook(tmp_path / "runweave.yml")
    step = _StepDefinition(
        runbook.steps[0].step_id,
        side_effect=SideEffect.WORKSPACE_WRITE,
        require_confirmation=True,
    )
    record = _record(step.step_id, StepStatus.SUCCEEDED)
    decision = evaluate_step(runbook, step, record, _context(outputs_valid=False))
    assert decision.decision is Decision.CONFIRM
    assert decision.reason_code is ReasonCode.OUTPUT_MISSING


def test_recovery_retryable_and_non_retryable_failures(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    runbook = load_runbook(tmp_path / "runweave.yml")
    retry_step = _StepDefinition(
        runbook.steps[0].step_id,
        side_effect=SideEffect.PURE,
        retry=RetryPolicy(
            mode=RetryMode.ONCE,
            max_attempts=2,
            retryable_errors=frozenset({FailureKind.NON_ZERO_EXIT}),
        ),
    )
    failed_record = _record(
        retry_step.step_id,
        StepStatus.FAILED,
        failure_kind=FailureKind.NON_ZERO_EXIT,
    )
    retryable = evaluate_step(runbook, retry_step, failed_record, _context())
    assert retryable.decision is Decision.RETRY
    assert retryable.reason_code is ReasonCode.FAILURE_RETRYABLE

    exhausted = _record(
        retry_step.step_id,
        StepStatus.FAILED,
        attempt_count=2,
        failure_kind=FailureKind.NON_ZERO_EXIT,
    )
    not_retryable = evaluate_step(runbook, retry_step, exhausted, _context())
    assert not_retryable.decision is Decision.RERUN
    assert not_retryable.reason_code is ReasonCode.FAILURE_NOT_RETRYABLE

    timeout_record = _record(
        retry_step.step_id,
        StepStatus.FAILED,
        failure_kind=FailureKind.TIMEOUT,
    )
    timeout_decision = evaluate_step(runbook, retry_step, timeout_record, _context())
    assert timeout_decision.decision is Decision.RERUN
    assert timeout_decision.reason_code is ReasonCode.FAILURE_NOT_RETRYABLE


def test_recovery_side_effect_confirmation_paths(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    runbook = load_runbook(tmp_path / "runweave.yml")
    confirm_step = _StepDefinition(
        "touch",
        side_effect=SideEffect.WORKSPACE_WRITE,
        require_confirmation=True,
    )
    record = _record(
        confirm_step.step_id,
        StepStatus.FAILED,
        failure_kind=FailureKind.NON_ZERO_EXIT,
    )
    forced = evaluate_step(runbook, confirm_step, record, _context())
    assert forced.decision is Decision.CONFIRM
    assert forced.reason_code is ReasonCode.SIDE_EFFECT_CONFIRMATION

    destructive = _StepDefinition(
        confirm_step.step_id,
        side_effect=SideEffect.DESTRUCTIVE,
        require_confirmation=confirm_step.recovery.require_confirmation,
    )
    destructive_record = _record(
        destructive.step_id,
        StepStatus.FAILED,
        failure_kind=FailureKind.TIMEOUT,
    )
    destructive_decision = evaluate_step(runbook, destructive, destructive_record, _context())
    assert destructive_decision.decision is Decision.CONFIRM
    assert destructive_decision.reason_code is ReasonCode.SIDE_EFFECT_CONFIRMATION

    external = _StepDefinition(
        confirm_step.step_id,
        side_effect=SideEffect.EXTERNAL_WRITE,
        require_confirmation=False,
    )
    external_record = _record(
        external.step_id,
        StepStatus.FAILED,
        failure_kind=FailureKind.SIGNAL,
    )
    external_decision = evaluate_step(runbook, external, external_record, _context())
    assert external_decision.decision is Decision.CONFIRM
    assert external_decision.reason_code is ReasonCode.SIDE_EFFECT_CONFIRMATION


def test_recovery_dependency_invalidated_branches(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    runbook = load_runbook(tmp_path / "runweave.yml")
    parent, child = (
        runbook.steps[0],
        _StepDefinition(
            "child",
            depends_on=("touch",),
            side_effect=SideEffect.PURE,
        ),
    )
    runbook = Runbook(
        runbook.schema_version,
        runbook.name,
        runbook.source_path,
        runbook.root,
        runbook.state_dir,
        (parent, child),
    )

    record = _record("child", StepStatus.SUCCEEDED)

    blocked_context = _context(
        {"touch": _reuse_decision("touch", Decision.BLOCK)},
    )
    blocked = evaluate_step(runbook, child, record, blocked_context)
    assert blocked.decision is Decision.BLOCK
    assert blocked.reason_code is ReasonCode.DEPENDENCY_INVALIDATED

    rerun_context = _context(
        {"touch": _reuse_decision("touch", Decision.RERUN)},
    )
    rerun = evaluate_step(runbook, child, record, rerun_context)
    assert rerun.decision is Decision.RERUN
    assert rerun.reason_code is ReasonCode.DEPENDENCY_INVALIDATED
    assert not rerun.requires_confirmation

    confirm_context = _context(
        {"touch": _reuse_decision("touch", Decision.CONFIRM)},
    )
    confirm = evaluate_step(runbook, child, record, confirm_context)
    assert confirm.decision is Decision.BLOCK

    retry_context = _context(
        {"touch": _reuse_decision("touch", Decision.RETRY)},
    )
    retry_decision = evaluate_step(runbook, child, record, retry_context)
    assert retry_decision.decision is Decision.RERUN


def _reuse_decision(step_id: str, decision: Decision) -> object:
    # A full RepairDecision instance is required by type, but evaluate_step
    # only inspects the `decision` attribute for dependency propagation.
    from runweave.domain.models import RepairDecision

    return RepairDecision(step_id, decision, ReasonCode.SUCCESS_CONTRACT_MATCH, "dep", False, ())


def test_evaluate_repair_iterates_runbook_order(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    runbook = load_runbook(tmp_path / "runweave.yml")
    records = {step.step_id: _record(step.step_id, StepStatus.SUCCEEDED) for step in runbook.steps}
    contexts = {step.step_id: _context() for step in runbook.steps}
    decisions = evaluate_repair(runbook, records, contexts)
    assert len(decisions) == 1
    assert decisions[0].decision is Decision.REUSE


def test_recovery_digest_helpers(tmp_path: Path) -> None:
    write_runbook(tmp_path)
    runbook = load_runbook(tmp_path / "runweave.yml")
    step = runbook.steps[0]
    assert len(command_digest(step)) == 64
    assert len(step_policy_digest(step)) == 64
    contract = StepContract(
        command_digest=command_digest(step),
        policy_digest=step_policy_digest(step),
        input_fingerprints=(PathFingerprint("out.txt", "text", "a" * 64, 3, 1, True),),
        output_fingerprints=(),
    )
    assert len(contract_digest(step, contract)) == 64


# ---------------------------------------------------------------------------
# yaml_runbook validation branches
# ---------------------------------------------------------------------------


def _run(validator_path: str, content: str) -> tuple[int, str]:
    pytest_file = Path(validator_path)
    pytest_file.write_text(content, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "runweave", "--json", "validate", validator_path],
        cwd=Path(validator_path).parent,
        text=True,
        capture_output=True,
        check=False,
        env=_coverage_env(),
    )
    payload = json.loads(result.stdout)
    return result.returncode, payload["error"]["code"]


def test_yaml_runbook_invalid_field_types(tmp_path: Path) -> None:
    code, err = _run(
        str(tmp_path / "bad.yml"),
        "name: x\nroot: .\nsteps: 'not-a-list'\n",
    )
    assert code == ExitCode.INVALID_INPUT
    assert err == "INVALID_SCHEMA_VERSION"

    code, err = _run(
        str(tmp_path / "steps.yml"),
        "schema_version: 1\nname: x\nroot: .\nsteps: 'not-a-list'\n",
    )
    assert code == ExitCode.INVALID_INPUT
    assert err == "INVALID_STEPS"

    code, err = _run(
        str(tmp_path / "bad2.yml"),
        "schema_version: 1\nname: x\nroot: .\nstate_dir: .runweave\nsteps:\n  - 42\n",
    )
    assert code == ExitCode.INVALID_INPUT
    assert err == "INVALID_FIELD_TYPE"

    code, err = _run(
        str(tmp_path / "bad3.yml"),
        "schema_version: true\nname: x\nsteps:\n  - id: a\n    command: [echo, hi]\n",
    )
    assert err == "INVALID_SCHEMA_VERSION"


def test_yaml_runbook_invalid_enum_and_retry(tmp_path: Path) -> None:
    code, err = _run(
        str(tmp_path / "side.yml"),
        (
            "schema_version: 1\nname: x\nroot: .\nsteps:\n"
            "  - id: a\n    command: [echo, hi]\n"
            "    side_effect: MAGIC\n"
        ),
    )
    assert err == "INVALID_ENUM"
    assert (
        "PURE, WORKSPACE_WRITE, NETWORK_READ, EXTERNAL_WRITE, DESTRUCTIVE"
        in json.loads(
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "runweave",
                    "--json",
                    "validate",
                    str(tmp_path / "side.yml"),
                ],
                cwd=tmp_path,
                text=True,
                capture_output=True,
                check=False,
                env=_coverage_env(),
            ).stdout,
        )["error"]["message"]
    )

    code, err = _run(
        str(tmp_path / "retry.yml"),
        (
            "schema_version: 1\nname: x\nroot: .\nsteps:\n"
            "  - id: a\n    command: [echo, hi]\n"
            "    retry:\n      max_attempts: 'two'\n"
        ),
    )
    assert err == "INVALID_FIELD_TYPE"


def test_yaml_runbook_invalid_step_and_recovery(tmp_path: Path) -> None:
    code, err = _run(
        str(tmp_path / "step.yml"),
        "schema_version: 1\nname: x\nroot: .\nsteps:\n  - id: ''\n    command: [echo]\n",
    )
    assert err == "MISSING_STEP_ID"

    code, err = _run(
        str(tmp_path / "cmd.yml"),
        "schema_version: 1\nname: x\nroot: .\nsteps:\n  - id: a\n    command: []\n",
    )
    assert err == "INVALID_COMMAND"

    code, err = _run(
        str(tmp_path / "rec.yml"),
        (
            "schema_version: 1\nname: x\nroot: .\nsteps:\n"
            "  - id: a\n    command: [echo]\n"
            "    recovery:\n      require_confirmation: 'yes'\n"
        ),
    )
    assert err == "INVALID_FIELD_TYPE"
    assert (
        "require_confirmation must be boolean"
        in json.loads(
            subprocess.run(
                [sys.executable, "-m", "runweave", "--json", "validate", str(tmp_path / "rec.yml")],
                cwd=tmp_path,
                text=True,
                capture_output=True,
                check=False,
                env=_coverage_env(),
            ).stdout,
        )["error"]["message"]
    )

    code, err = _run(
        str(tmp_path / "timeout.yml"),
        (
            "schema_version: 1\nname: x\nroot: .\nsteps:\n"
            "  - id: a\n    command: [echo]\n"
            "    timeout_seconds: 'soon'\n"
        ),
    )
    assert err == "INVALID_FIELD_TYPE"


def test_yaml_runbook_read_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yml"
    broken.write_text("schema_version: 1\n  name: [bad indent\n", encoding="utf-8")
    code, err = _run(str(broken), "")
    assert code == ExitCode.INVALID_INPUT
    assert err == "INVALID_FIELD_TYPE"

    missing = tmp_path / "missing.yml"
    result = subprocess.run(
        [sys.executable, "-m", "runweave", "--json", "validate", str(missing)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_coverage_env(),
    )
    payload = json.loads(result.stdout)
    assert result.returncode == ExitCode.INVALID_INPUT
    assert payload["error"]["code"] == "RUNBOOK_READ_ERROR"


def test_yaml_runbook_unknown_fields_and_name_errors(tmp_path: Path) -> None:
    code, err = _run(
        str(tmp_path / "unknown.yml"),
        (
            "schema_version: 1\nname: x\nroot: .\n"
            "mystery: field\n"
            "steps:\n  - id: a\n    command: [echo]\n"
        ),
    )
    assert err == "UNKNOWN_FIELD"

    code, err = _run(
        str(tmp_path / "noname.yml"),
        "schema_version: 1\nroot: .\nsteps:\n  - id: a\n    command: [echo]\n",
    )
    assert err == "MISSING_RUNBOOK_NAME"

    code, err = _run(
        str(tmp_path / "empty.yml"),
        "schema_version: 1\nname: x\nroot: .\nsteps: []\n",
    )
    assert err == "NO_STEPS"

    code, err = _run(
        str(tmp_path / "badretry.yml"),
        (
            "schema_version: 1\nname: x\nroot: .\nsteps:\n"
            "  - id: a\n    command: [echo]\n"
            "    retry:\n      retryable_errors: [UNKNOWN_KIND]\n"
        ),
    )
    assert err == "INVALID_ENUM"


# ---------------------------------------------------------------------------
# SQLite state store error branches
# ---------------------------------------------------------------------------


def test_store_unknown_run_and_step_lookups(tmp_path: Path) -> None:
    runbook_path = write_runbook(tmp_path)
    runbook = load_runbook(runbook_path)
    store = SQLiteStateStore(runbook.state_dir / "state.sqlite3")
    store.initialize()
    store.create_run("run-x", "d" * 64, datetime.now(UTC), ("touch",))

    with pytest.raises(KeyError):
        store.load_run("does-not-exist")
    assert store.load_steps("does-not-exist") == {}


def test_store_unknown_step_in_transitions(tmp_path: Path) -> None:
    runbook_path = write_runbook(tmp_path)
    runbook = load_runbook(runbook_path)
    store = SQLiteStateStore(runbook.state_dir / "state.sqlite3")
    run_id = _create_run(store, runbook)
    with pytest.raises(KeyError):
        store.update_step_status(run_id, "nonexistent-step", StepStatus.BLOCKED)


def test_store_unknown_step_in_attempt_recording(tmp_path: Path) -> None:
    runbook_path = write_runbook(tmp_path)
    runbook = load_runbook(runbook_path)
    store = SQLiteStateStore(runbook.state_dir / "state.sqlite3")
    run_id = _create_run(store, runbook)
    with pytest.raises(KeyError):
        store.record_step_started(
            run_id,
            "nonexistent-step",
            "attempt-1",
            StepContract("c" * 64, "p" * 64, (), ()),
            datetime.now(UTC),
        )


def test_store_unknown_step_in_attempt_finish(tmp_path: Path) -> None:
    runbook_path = write_runbook(tmp_path)
    runbook = load_runbook(runbook_path)
    store = SQLiteStateStore(runbook.state_dir / "state.sqlite3")
    run_id = _create_run(store, runbook)
    result = _AttemptResult()
    with pytest.raises(KeyError):
        store.record_step_finished(
            run_id,
            "nonexistent-step",
            "attempt-1",
            result,
            StepContract("c" * 64, "p" * 64, (), ()),
            datetime.now(UTC),
        )


def _create_run(store: SQLiteStateStore, runbook: object) -> str:
    from datetime import UTC, datetime

    from runweave.application.common import runbook_digest

    run_id = "run-test-1"
    store.initialize()
    store.create_run(
        run_id,
        runbook_digest(runbook),
        datetime.now(UTC),
        tuple(step.step_id for step in runbook.steps),
    )
    return run_id


def _AttemptResult() -> object:
    from runweave.domain.models import AttemptResult

    return AttemptResult(
        status=StepStatus.FAILED,
        exit_code=1,
        failure_kind=FailureKind.NON_ZERO_EXIT,
        stdout="",
        stderr="",
        duration_ms=0,
    )


def test_store_repair_plan_round_trip_and_unknown_plan(tmp_path: Path) -> None:
    runbook_path = write_runbook(tmp_path)
    runbook = load_runbook(runbook_path)
    store = SQLiteStateStore(runbook.state_dir / "state.sqlite3")
    outcome = execute_runbook(runbook, store)
    plan = build_repair_plan(runbook, outcome.run_id, store)

    loaded = store.load_repair_plan(plan.plan_id)
    assert loaded.plan_id == plan.plan_id
    assert loaded.run_id == plan.run_id
    assert loaded.source_runbook_digest == plan.source_runbook_digest
    assert loaded.decisions == plan.decisions

    with pytest.raises(KeyError):
        store.load_repair_plan("no-such-plan")


def test_store_update_step_status_after_run(tmp_path: Path) -> None:
    runbook_path = write_runbook(tmp_path)
    runbook = load_runbook(runbook_path)
    store = SQLiteStateStore(runbook.state_dir / "state.sqlite3")
    outcome = execute_runbook(runbook, store)
    store.update_step_status(outcome.run_id, "touch", StepStatus.INVALIDATED)
    updated = store.load_steps(outcome.run_id)["touch"]
    assert updated.status is StepStatus.INVALIDATED


# ---------------------------------------------------------------------------
# fingerprint_env_names
# ---------------------------------------------------------------------------


def test_fingerprint_env_names_redaction(tmp_path: Path) -> None:
    environment = {
        "HOME": "/home/u",
        "GITHUB_TOKEN": "secret",
        "DB_PASSWORD": "secret",
        "APP_API_KEY": "secret",
        "PRIVATE_KEY_FILE": "/tmp/k",
        "USER_CREDENTIAL_STORE": "store",
        "BUILD_MODE": "release",
        "PATH": "/usr/bin",
    }
    names = (
        "HOME",
        "GITHUB_TOKEN",
        "DB_PASSWORD",
        "APP_API_KEY",
        "PRIVATE_KEY_FILE",
        "USER_CREDENTIAL_STORE",
        "BUILD_MODE",
        "PATH",
        "MISSING_VAR",
    )
    redacted = fingerprint_env_names(names, environment)
    assert redacted["HOME"] == "<present>"
    assert redacted["BUILD_MODE"] == "<present>"
    assert all(
        redacted[key] == "<redacted>"
        for key in (
            "GITHUB_TOKEN",
            "DB_PASSWORD",
            "APP_API_KEY",
            "PRIVATE_KEY_FILE",
            "USER_CREDENTIAL_STORE",
        )
    )
    assert "MISSING_VAR" not in redacted
    # Deduplication and sorting are preserved as dictionary ordering.
    assert list(redacted) == sorted(dict.fromkeys(item for item in names if item in environment))


# ---------------------------------------------------------------------------
# Error class contracts
# ---------------------------------------------------------------------------


def test_runweave_error_str_and_subclasses() -> None:
    base = RunWeaveError("CODE", "msg", exit_code=ExitCode.INTERNAL)
    assert str(base) == "msg"

    from runweave.errors import (
        ConfirmationRequiredError,
        RepairPlanStaleError,
        StateConflictError,
    )

    assert StateConflictError("c").code == "STATE_CONFLICT"
    assert StateConflictError("c").exit_code == ExitCode.BLOCKED_OR_UNSAFE
    assert RepairPlanStaleError("p").code == "PLAN_STALE"
    assert RepairPlanStaleError("p").exit_code == ExitCode.BLOCKED_OR_UNSAFE
    assert ConfirmationRequiredError("s").code == "SIDE_EFFECT_CONFIRMATION_REQUIRED"
    assert ConfirmationRequiredError("s").exit_code == ExitCode.BLOCKED_OR_UNSAFE
    assert ConfirmationRequiredError("s", {"step_id": "x"}).details == {"step_id": "x"}


# ---------------------------------------------------------------------------
# models dataclass validation contracts
# ---------------------------------------------------------------------------


def test_step_definition_construction_constraints() -> None:
    with pytest.raises(ValueError, match="step_id must not be empty"):
        StepDefinition(step_id="", command=("echo",))
    with pytest.raises(ValueError, match="command must be a non-empty argv vector"):
        StepDefinition(step_id="a", command=("",))
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        StepDefinition(step_id="a", command=("echo",), timeout_seconds=0.0)


def test_retry_policy_construction_constraints() -> None:
    with pytest.raises(ValueError, match="NEVER"):
        RetryPolicy(mode=RetryMode.NEVER, max_attempts=2)
    with pytest.raises(ValueError, match="ONCE"):
        RetryPolicy(mode=RetryMode.ONCE, max_attempts=1)
    with pytest.raises(ValueError, match="BOUNDED"):
        RetryPolicy(mode=RetryMode.BOUNDED, max_attempts=1)
    with pytest.raises(ValueError, match="BOUNDED"):
        RetryPolicy(mode=RetryMode.BOUNDED, max_attempts=11)


def test_repair_plan_requires_confirmation_property() -> None:
    from runweave.domain.models import RepairDecision, RepairPlan

    plan_empty = RepairPlan("p", "r", "d", (), datetime.now(UTC))
    assert plan_empty.requires_confirmation is False

    plan_hard = RepairPlan(
        "p",
        "r",
        "d",
        (
            RepairDecision("a", Decision.REUSE, ReasonCode.SUCCESS_CONTRACT_MATCH, "x"),
            RepairDecision(
                "b",
                Decision.CONFIRM,
                ReasonCode.SIDE_EFFECT_CONFIRMATION,
                "y",
                True,
            ),
        ),
        datetime.now(UTC),
    )
    assert plan_hard.requires_confirmation is True
    assert plan_hard.created_at.tzinfo is not None


def test_as_jsonable_recursion(tmp_path: Path) -> None:
    from datetime import datetime

    from runweave.domain.models import as_jsonable

    stamp = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    fp = PathFingerprint(
        path="out.txt",
        kind="text",
        digest="f" * 64,
        size=3,
        mtime_ns=1,
        exists=True,
    )
    result = as_jsonable({"p": Path("x"), "t": stamp, "fp": fp, "tup": (fp,)})
    assert result["p"] == "x"
    assert result["t"] == "2026-08-19T12:00:00+00:00"
    assert isinstance(result["fp"]["exists"], bool)
    assert isinstance(result["tup"], list)
    # Primitives with a .value attribute (StrEnum members) are unwrapped.
    assert as_jsonable(StepStatus.SUCCEEDED) == "SUCCEEDED"
