from __future__ import annotations

import os
import signal
import subprocess
import time

from runweave.domain.enums import FailureKind, StepStatus
from runweave.domain.models import AttemptResult
from runweave.ports.interfaces import CommandContext, CommandRunner

_MAX_LOG_BYTES = 512 * 1024


def _bounded(value: bytes) -> str:
    if len(value) <= _MAX_LOG_BYTES:
        return value.decode("utf-8", errors="replace")
    suffix = "\n[runweave] log truncated at 512 KiB\n"
    return value[: _MAX_LOG_BYTES - len(suffix.encode())].decode("utf-8", errors="replace") + suffix


class LocalCommandRunner(CommandRunner):
    def run(self, context: CommandContext) -> AttemptResult:
        started = time.monotonic()
        environment = os.environ.copy()
        environment.update(context.environment)
        try:
            process = subprocess.Popen(
                list(context.argv),
                cwd=context.cwd,
                env=environment,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=context.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                os.killpg(process.pid, signal.SIGTERM)
                stdout, stderr = process.communicate()
                return AttemptResult(
                    StepStatus.FAILED,
                    process.returncode,
                    FailureKind.TIMEOUT,
                    _bounded(stdout or exc.stdout or b""),
                    _bounded(stderr or exc.stderr or b""),
                    int((time.monotonic() - started) * 1000),
                    "TIMEOUT",
                )
        except OSError as exc:
            return AttemptResult(
                StepStatus.FAILED,
                None,
                FailureKind.INTERNAL,
                "",
                str(exc),
                int((time.monotonic() - started) * 1000),
                "PROCESS_START_ERROR",
            )

        if process.returncode == 0:
            return AttemptResult(
                StepStatus.SUCCEEDED,
                0,
                None,
                _bounded(stdout),
                _bounded(stderr),
                int((time.monotonic() - started) * 1000),
            )
        failure_kind = FailureKind.SIGNAL if process.returncode < 0 else FailureKind.NON_ZERO_EXIT
        return AttemptResult(
            StepStatus.FAILED,
            process.returncode,
            failure_kind,
            _bounded(stdout),
            _bounded(stderr),
            int((time.monotonic() - started) * 1000),
            "SIGNAL" if process.returncode < 0 else "NON_ZERO_EXIT",
        )
