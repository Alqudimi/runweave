from pathlib import Path

import pytest

from runweave.adapters.yaml_runbook import load_runbook
from runweave.domain.validation import execution_plan
from runweave.errors import RunbookValidationError


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_runbook_has_deterministic_plan(tmp_path: Path) -> None:
    path = write(
        tmp_path / "runweave.yml",
        """schema_version: 1
name: test
steps:
  - id: b
    command: [python, -c, 'print(2)']
    depends_on: [a]
  - id: a
    command: [python, -c, 'print(1)']
""",
    )
    runbook = load_runbook(path)
    plan = execution_plan(runbook)
    assert plan.order == ("a", "b")
    assert plan.levels == (("a",), ("b",))
    assert len(plan.digest) == 64


def test_unknown_dependency_is_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path / "runweave.yml",
        """schema_version: 1
name: test
steps:
  - id: a
    command: [python, -c, 'print(1)']
    depends_on: [missing]
""",
    )
    with pytest.raises(RunbookValidationError) as error:
        load_runbook(path)
    assert error.value.code == "UNKNOWN_DEPENDENCY"


def test_cycle_is_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path / "runweave.yml",
        """schema_version: 1
name: test
steps:
  - id: a
    command: [python, -c, 'print(1)']
    depends_on: [b]
  - id: b
    command: [python, -c, 'print(2)']
    depends_on: [a]
""",
    )
    with pytest.raises(RunbookValidationError) as error:
        load_runbook(path)
    assert error.value.code == "DEPENDENCY_CYCLE"


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path / "runweave.yml",
        """schema_version: 1
name: test
unexpected: true
steps:
  - id: a
    command: [python, -c, 'print(1)']
""",
    )
    with pytest.raises(RunbookValidationError) as error:
        load_runbook(path)
    assert error.value.code == "UNKNOWN_FIELD"
