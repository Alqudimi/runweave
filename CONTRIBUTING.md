# Contributing to RunWeave

Thank you for contributing. RunWeave is a safety-sensitive developer tool: a change that makes recovery less explicit or weakens the command boundary is more important than a small feature addition. Please read the product specification, architecture document, and runbook schema before changing domain behavior.

## Development setup

Use Python 3.11 or newer and install the project with development dependencies:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run formatting, linting, typing, tests, and package builds before opening a pull request:

```bash
ruff format src tests
ruff check src tests
mypy src
pytest -q
python -m build --wheel --sdist --outdir dist
```

## Design rules

Domain decisions belong under `src/runweave/domain/` and must not import SQLite, YAML, CLI parsing, or subprocess details. Application services coordinate use cases through ports. Adapters may depend on the domain and ports, but the domain must remain testable without infrastructure.

New public status values, decision values, reason codes, runbook fields, or JSON fields are compatibility commitments. Prefer additive changes, update the schema documentation, and add tests for both the new behavior and stale/invalid input. Never make a resume decision based only on the presence of an output file.

Commands must remain argument vectors executed with `shell=False` by default. Do not add implicit shell interpolation, broad environment persistence, undeclared filesystem scanning, or automatic retries for external and destructive side effects.

## Pull requests

A pull request should explain the user problem, the safety implications, the affected contracts, and the verification evidence. Include a focused test for every new reason code or state transition. If a change affects the CLI, include a human-readable example and a JSON-output assertion.

Keep commits small and descriptive. Generated state databases, virtual environments, build artifacts, coverage files, and secrets must not be committed. New dependencies require a short rationale and an update to the package metadata.

## Security reports

Please do not open a public issue for a suspected command-injection, path-traversal, secret-leakage, or unsafe-resume vulnerability. Follow the process in [`SECURITY.md`](SECURITY.md).
