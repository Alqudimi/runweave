from pathlib import Path

from runweave.adapters.subprocess_runner import LocalCommandRunner
from runweave.domain.enums import FailureKind, StepStatus
from runweave.ports.interfaces import CommandContext


def context(tmp_path: Path, *args: str, timeout: float = 5.0) -> CommandContext:
    return CommandContext(args, tmp_path, {}, timeout)


def test_runner_preserves_argument_boundaries(tmp_path: Path) -> None:
    result = LocalCommandRunner().run(
        context(tmp_path, "python", "-c", "import sys; print(sys.argv[1])", "a b")
    )
    assert result.status is StepStatus.SUCCEEDED
    assert result.stdout.strip() == "a b"


def test_runner_classifies_non_zero_exit(tmp_path: Path) -> None:
    result = LocalCommandRunner().run(context(tmp_path, "python", "-c", "raise SystemExit(7)"))
    assert result.status is StepStatus.FAILED
    assert result.failure_kind is FailureKind.NON_ZERO_EXIT
    assert result.exit_code == 7


def test_runner_classifies_timeout(tmp_path: Path) -> None:
    result = LocalCommandRunner().run(
        context(tmp_path, "python", "-c", "import time; time.sleep(2)", timeout=0.05)
    )
    assert result.status is StepStatus.FAILED
    assert result.failure_kind is FailureKind.TIMEOUT
