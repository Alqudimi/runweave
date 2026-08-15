from __future__ import annotations

import hashlib
from pathlib import Path

from runweave.errors import RunbookValidationError

from .models import PathFingerprint

_CHUNK_SIZE = 1024 * 1024


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()


def _fingerprint_file(root: Path, path: Path, relative: str) -> PathFingerprint:
    stat = path.stat()
    return PathFingerprint(
        relative,
        "file",
        _hash_file(path),
        stat.st_size,
        stat.st_mtime_ns,
        True,
    )


def fingerprint_path(
    root: Path,
    relative: str,
    *,
    reject_symlinks: bool = True,
) -> PathFingerprint:
    root = root.resolve()
    path = (root / relative).resolve(strict=False)
    if path != root and root not in path.parents:
        raise RunbookValidationError(
            "PATH_OUTSIDE_ROOT",
            f"Declared path escapes workspace root: {relative}",
            {"path": relative},
        )
    original = root / relative
    has_symlink_parent = any(parent.is_symlink() for parent in original.parents if parent != root)
    if reject_symlinks and (original.is_symlink() or has_symlink_parent):
        raise RunbookValidationError(
            "SYMLINK_NOT_ALLOWED",
            f"Symlink path is not allowed by default: {relative}",
            {"path": relative},
        )
    if not original.exists():
        return PathFingerprint(relative, "missing", None, None, None, False)
    if original.is_file():
        return _fingerprint_file(root, original, relative)
    if original.is_dir():
        entries: list[PathFingerprint] = []
        for item in sorted(original.rglob("*")):
            item_relative = item.relative_to(root).as_posix()
            if item.is_symlink() and reject_symlinks:
                raise RunbookValidationError(
                    "SYMLINK_NOT_ALLOWED",
                    f"Symlink path is not allowed by default: {item_relative}",
                    {"path": item_relative},
                )
            if item.is_file():
                entries.append(_fingerprint_file(root, item, item_relative))
        hasher = hashlib.sha256()
        for entry in entries:
            hasher.update(f"{entry.path}:{entry.digest}:{entry.size}".encode())
        stat = original.stat()
        return PathFingerprint(
            relative,
            "directory",
            hasher.hexdigest(),
            len(entries),
            stat.st_mtime_ns,
            True,
        )
    stat = original.stat()
    return PathFingerprint(
        relative,
        "other",
        None,
        stat.st_size,
        stat.st_mtime_ns,
        True,
    )


def fingerprint_paths(root: Path, paths: tuple[str, ...]) -> tuple[PathFingerprint, ...]:
    return tuple(fingerprint_path(root, path) for path in sorted(set(paths)))


def outputs_are_valid(fingerprints: tuple[PathFingerprint, ...]) -> bool:
    return bool(all(item.exists for item in fingerprints)) if fingerprints else True


def fingerprint_env_names(names: tuple[str, ...], environment: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    secret_markers = (
        "TOKEN",
        "PASSWORD",
        "SECRET",
        "API_KEY",
        "PRIVATE_KEY",
        "CREDENTIAL",
    )
    for name in sorted(set(names)):
        if name not in environment:
            continue
        is_secret = any(marker in name.upper() for marker in secret_markers)
        redacted[name] = "<redacted>" if is_secret else "<present>"
    return redacted
