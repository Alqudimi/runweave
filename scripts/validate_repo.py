from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "pyproject.toml",
    ".github/workflows/ci.yml",
    "docs/product-spec.md",
    "docs/architecture.md",
    "docs/runbook-schema.md",
    "docs/verification.md",
)


def main() -> None:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    if missing:
        raise SystemExit(f"Missing required files: {', '.join(missing)}")

    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    if not isinstance(workflow, dict) or "jobs" not in workflow:
        raise SystemExit("CI workflow must contain a jobs mapping")
    if "quality" not in workflow["jobs"] or "security" not in workflow["jobs"]:
        raise SystemExit("CI workflow must contain quality and security jobs")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", readme)
    broken = [
        link
        for link in links
        if not link.startswith(("http://", "https://")) and not (ROOT / link).exists()
    ]
    if broken:
        raise SystemExit(f"Broken local README links: {', '.join(broken)}")

    forbidden = (".venv", ".runweave", "coverage.json", "dist/")
    tracked_candidates = [path for path in forbidden if (ROOT / path).exists()]
    if tracked_candidates:
        print(
            f"Note: generated paths exist locally and are ignored: {', '.join(tracked_candidates)}"
        )
    print(f"Validated {len(REQUIRED_FILES)} required release files, CI jobs, and README links.")


if __name__ == "__main__":
    main()
