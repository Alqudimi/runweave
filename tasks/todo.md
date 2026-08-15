# RunWeave Task Checklist

## Foundation

- [x] Task 1: Package and configuration foundation
- [x] Task 2: Domain runbook and validation contracts
- [x] Task 3: State machine and contract evaluation

### Checkpoint: domain correctness

- [x] Domain tests pass without infrastructure adapters
- [x] Status enums and reason codes are documented
- [x] CLI contains no business rules

## Persistence and adapters

- [x] Task 4: SQLite state store and migrations
- [x] Task 5: Safe filesystem observer
- [x] Task 6: Safe subprocess runner

### Checkpoint: adapter safety

- [x] SQLite integration tests pass
- [x] Filesystem security tests pass
- [x] Subprocess timeout and shell-boundary tests pass

## MVP user journey

- [x] Task 7: Validate, init, and plan commands
- [x] Task 8: Run, status, and inspect commands
- [x] Task 9: Repair and resume commands

### Checkpoint: MVP user journey

- [x] Clean init → validate → plan → run → inspect → repair → resume flow works
- [x] Sample success, failure, and recovery scenarios work
- [x] Exit codes and JSON output are documented and stable

## Hardening and release

- [x] Task 10: Exporters, docs, examples, and benchmarks
- [x] Task 11: Security, static checks, and CI
- [x] Task 12: Open-source governance and release packaging

### Final checkpoint

- [x] Clean-clone install passes
- [x] All tests, lint, type checks, build, security checks, and documentation checks pass
- [ ] GitHub Actions workflow has been verified after push
- [x] Release notes and final evidence are complete
