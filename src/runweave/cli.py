from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runweave.adapters.sqlite_store import SQLiteStateStore
from runweave.adapters.yaml_runbook import load_runbook
from runweave.application.common import runbook_digest
from runweave.application.execution import (
    ExecutionOutcome,
    execute_runbook,
    resume_runbook,
)
from runweave.application.repair import build_repair_plan
from runweave.domain.models import Runbook, as_jsonable
from runweave.domain.validation import execution_plan
from runweave.errors import ExitCode, RunWeaveError

_SCHEMA_VERSION = 1
_STARTER = """schema_version: 1
name: sample-runbook
root: .
state_dir: .runweave
steps:
  - id: prepare
    command:
      - python
      - -c
      - |
        from pathlib import Path
        Path("build").mkdir(exist_ok=True)
        Path("build/hello.txt").write_text("hello\\n")
    outputs: [build/hello.txt]
    side_effect: WORKSPACE_WRITE
    retry:
      mode: NEVER
  - id: verify
    command:
      - python
      - -c
      - |
        from pathlib import Path
        assert Path("build/hello.txt").read_text() == "hello\\n"
    depends_on: [prepare]
    inputs: [build/hello.txt]
    side_effect: PURE
    retry:
      mode: ONCE
      retryable_errors: [NON_ZERO_EXIT]
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runweave",
        description="Safe, resumable repository runbooks.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create a starter runbook.")
    init.add_argument("path", nargs="?", type=Path, default=Path("runweave.yml"))
    basic_commands = (
        ("validate", "Validate a runbook."),
        ("plan", "Show execution plan."),
        ("run", "Execute a new run."),
    )
    for name, help_text in basic_commands:
        command = sub.add_parser(name, help=help_text)
        command.add_argument("runbook", type=Path)
    inspection_commands = (
        ("status", "Show run status."),
        ("inspect", "Inspect current run state."),
        ("repair", "Generate a non-executing repair plan."),
        ("export", "Export run evidence."),
    )
    for name, help_text in inspection_commands:
        command = sub.add_parser(name, help=help_text)
        command.add_argument("run_id")
        command.add_argument("--runbook", type=Path, default=Path("runweave.yml"))
    resume = sub.add_parser("resume", help="Resume a run from a repair plan.")
    resume.add_argument("run_id")
    resume.add_argument("--runbook", type=Path, default=Path("runweave.yml"))
    resume.add_argument("--plan", required=True, dest="plan_id")
    resume.add_argument("--confirm-side-effects", nargs="*", default=[])
    return parser


def _emit(args: argparse.Namespace, data: Any, *, ok: bool = True) -> int:
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "ok": ok,
        "command": args.command,
        "data": as_jsonable(data),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif isinstance(data, str):
        print(data)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return ExitCode.OK


def _error(args: argparse.Namespace, error: RunWeaveError) -> int:
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "ok": False,
        "command": args.command,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details or {},
            "suggested_action": error.suggested_action,
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        if error.suggested_action:
            print(f"Suggested action: {error.suggested_action}", file=sys.stderr)
    return error.exit_code


def _store(runbook: Runbook) -> SQLiteStateStore:
    return SQLiteStateStore(runbook.state_dir / "state.sqlite3")


def _run_outcome(args: argparse.Namespace, outcome: ExecutionOutcome) -> int:
    succeeded = outcome.status.value == "SUCCEEDED"
    output_code = _emit(args, outcome, ok=succeeded)
    return output_code if succeeded else ExitCode.STEP_FAILURE


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            path = args.path.resolve()
            if path.exists():
                raise RunWeaveError(
                    "RUNBOOK_EXISTS",
                    f"Runbook already exists: {path}",
                    exit_code=ExitCode.INVALID_INPUT,
                )
            path.write_text(_STARTER, encoding="utf-8")
            return _emit(args, {"path": str(path), "message": "Starter runbook created."})

        if args.command in {"validate", "plan", "run"}:
            runbook = load_runbook(args.runbook)
            if args.command == "validate":
                return _emit(
                    args,
                    {
                        "valid": True,
                        "runbook_digest": runbook_digest(runbook),
                        "steps": len(runbook.steps),
                    },
                )
            if args.command == "plan":
                execution_plan_value = execution_plan(runbook)
                return _emit(
                    args,
                    {
                        "runbook_digest": runbook_digest(runbook),
                        "plan_digest": execution_plan_value.digest,
                        "order": execution_plan_value.order,
                        "levels": execution_plan_value.levels,
                    },
                )
            return _run_outcome(args, execute_runbook(runbook))

        runbook = load_runbook(args.runbook)
        store = _store(runbook)
        if args.command == "status":
            return _emit(
                args,
                {"run": store.load_run(args.run_id), "steps": store.load_steps(args.run_id)},
            )
        if args.command == "inspect":
            return _emit(
                args,
                {
                    "run": store.load_run(args.run_id),
                    "steps": store.load_steps(args.run_id),
                    "runbook_digest": runbook_digest(runbook),
                },
            )
        if args.command == "repair":
            return _emit(args, build_repair_plan(runbook, args.run_id, store))
        if args.command == "resume":
            repair_plan = store.load_repair_plan(args.plan_id)
            outcome = resume_runbook(
                runbook,
                args.run_id,
                repair_plan,
                store,
                set(args.confirm_side_effects),
            )
            return _run_outcome(args, outcome)
        if args.command == "export":
            return _emit(
                args,
                {"run": store.load_run(args.run_id), "steps": store.load_steps(args.run_id)},
            )
    except RunWeaveError as error:
        return _error(args, error)
    except KeyError as error:
        return _error(
            args,
            RunWeaveError("RUN_NOT_FOUND", str(error), exit_code=ExitCode.INVALID_INPUT),
        )
    except (OSError, ValueError, TypeError) as error:
        internal = RunWeaveError(
            "INTERNAL_ERROR",
            str(error),
            exit_code=ExitCode.INTERNAL,
        )
        return _error(args, internal)
    return ExitCode.INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
