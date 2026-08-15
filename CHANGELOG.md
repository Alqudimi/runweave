# Changelog

All notable changes to RunWeave are documented here.

## [0.1.0] - 2026-08-15

### Added

- Versioned YAML runbooks with dependency-aware validation and deterministic planning.
- Shell-free sequential command execution with bounded logs and timeout classification.
- SQLite persistence for runs, steps, attempts, contracts, and state transitions.
- Declared file and directory fingerprints with root and symlink safety checks.
- Repair-plan generation with reuse, retry, rerun, block, and confirmation decisions.
- Safe resume checks for stale runbooks, changed inputs, changed policies, and side-effecting steps.
- Stable JSON output, exit codes, CLI help, sample runbook, architecture documentation, tests, and CI.

### Known limitations

- Execution is single-process and sequential in the MVP.
- The engine observes declared local paths but cannot prove reproducibility of external services, clocks, networks, or mutable environments.
- RunWeave is not a sandbox and does not provide a hosted dashboard or remote state backend.
