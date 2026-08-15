from __future__ import annotations

from pathlib import Path

from runweave.domain.fingerprints import fingerprint_paths
from runweave.domain.models import PathFingerprint
from runweave.ports.interfaces import WorkspaceObserver


class LocalWorkspaceObserver(WorkspaceObserver):
    def fingerprint(self, root: Path, paths: tuple[str, ...]) -> tuple[PathFingerprint, ...]:
        return fingerprint_paths(root, paths)
