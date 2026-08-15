from pathlib import Path

import pytest

from runweave.domain.fingerprints import fingerprint_path, fingerprint_paths, outputs_are_valid
from runweave.errors import RunbookValidationError


def test_file_fingerprint_changes_when_content_changes(tmp_path: Path) -> None:
    target = tmp_path / "input.txt"
    target.write_text("one", encoding="utf-8")
    first = fingerprint_path(tmp_path, "input.txt")
    target.write_text("two", encoding="utf-8")
    second = fingerprint_path(tmp_path, "input.txt")
    assert first.digest != second.digest
    assert first.size == second.size


def test_directory_fingerprint_is_order_independent(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    directory.mkdir()
    (directory / "b.txt").write_text("b", encoding="utf-8")
    (directory / "a.txt").write_text("a", encoding="utf-8")
    first = fingerprint_path(tmp_path, "data")
    second = fingerprint_paths(tmp_path, ("data",))[0]
    assert first == second


def test_missing_output_is_not_valid(tmp_path: Path) -> None:
    fingerprints = fingerprint_paths(tmp_path, ("missing.txt",))
    assert not outputs_are_valid(fingerprints)


def test_symlink_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(source)
    with pytest.raises(RunbookValidationError) as error:
        fingerprint_path(tmp_path, "link.txt")
    assert error.value.code == "SYMLINK_NOT_ALLOWED"


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RunbookValidationError) as error:
        fingerprint_path(tmp_path, "../outside.txt")
    assert error.value.code == "PATH_OUTSIDE_ROOT"
