# Implementation Plan: RunWeave

## Overview

RunWeave is a Python 3.11+ local-first CLI that executes repository-native YAML runbooks with explicit step contracts, transactional SQLite state, safe subprocess boundaries, and explainable repair/resume behavior. The implementation proceeds bottom-up from domain contracts to adapters, then vertical CLI slices, followed by hardening and release evidence.

## Architecture decisions

The domain layer is framework-independent and owns the correctness rules. Application services coordinate use cases through ports. SQLite, filesystem hashing, subprocess execution, YAML parsing, and CLI presentation remain adapters. The MVP executes sequentially, uses `shell=False`, stores only declared path observations, and treats side effects as explicit policy rather than inferred behavior.

## Task list

### Phase 1: Foundation and contracts

#### Task 1: Package and configuration foundation

**Description:** Create the installable Python package, typed configuration objects, CLI entry point, package metadata, and stable error/exit-code definitions.

**Acceptance criteria:**

- [ ] `python -m runweave --help` and the installed `runweave --help` show the documented command surface.
- [ ] Python 3.11+ is declared and the package installs without runtime services.
- [ ] Configuration has safe defaults and does not read secrets implicitly.

**Verification:** Install the package in a clean virtual environment and run the help command.

**Dependencies:** None.

#### Task 2: Domain runbook and validation contracts

**Description:** Implement immutable domain models for runbooks, steps, policies, retry rules, canonical serialization, and validation errors.

**Acceptance criteria:**

- [ ] Valid runbooks parse into typed domain models with stable canonical digests.
- [ ] Duplicate IDs, unknown dependencies, cycles, unsafe paths, malformed commands, and invalid policies are rejected with stable error codes.
- [ ] Domain tests do not require YAML, SQLite, or subprocess execution.

**Verification:** Unit tests cover valid runbooks, all validation failures, canonical digest stability, and path boundary checks.

**Dependencies:** Task 1.

#### Task 3: State machine and contract evaluation

**Description:** Implement step/run states, legal transitions, attempt records, path fingerprints, contract digests, and reusable/invalidation decisions.

**Acceptance criteria:**

- [ ] Illegal transitions are rejected deterministically.
- [ ] File and directory fingerprints are streamed, sorted, and limited to declared paths.
- [ ] Contract evaluation explains reusable, invalidated, retryable, blocked, and confirmation-required decisions.

**Verification:** Unit tests cover transitions, changed inputs/outputs, missing outputs, policy changes, stale attempts, and redaction.

**Dependencies:** Task 2.

### Checkpoint: domain correctness

- [ ] Domain tests pass with no infrastructure adapters.
- [ ] Reason codes and status enums are documented and stable.
- [ ] No business rule is implemented in the CLI layer.

### Phase 2: Persistence and execution adapters

#### Task 4: SQLite state store and migrations

**Description:** Implement schema creation, version checks, transactional repositories, append-only transitions, attempt persistence, and repair-plan storage.

**Acceptance criteria:**

- [ ] A new state directory initializes safely and idempotently.
- [ ] Run/step/attempt/transition/fingerprint/repair-plan records survive process restart.
- [ ] A simulated crash cannot leave an uncommitted partial transition.

**Verification:** Integration tests use temporary SQLite databases and assert transactions, migrations, round trips, and stale-running detection.

**Dependencies:** Task 3.

#### Task 5: Safe filesystem observer

**Description:** Implement root-relative path resolution, symlink policy, bounded streaming hashes, metadata capture, output checks, and environment-name redaction.

**Acceptance criteria:**

- [ ] Paths outside the workspace root and symlink artifacts are rejected by default.
- [ ] Fingerprints are deterministic and do not read undeclared paths.
- [ ] Secret-looking environment names are redacted without persisting values.

**Verification:** Security-focused tests cover traversal, symlink, large-file streaming, missing paths, permissions, and redaction cases.

**Dependencies:** Task 3.

#### Task 6: Safe subprocess runner

**Description:** Implement argument-vector execution with `shell=False`, working-directory validation, bounded log capture, timeout handling, signal classification, and deterministic result objects.

**Acceptance criteria:**

- [ ] Commands execute without shell interpolation and preserve argument boundaries.
- [ ] Timeouts and non-zero exits produce stable failure classifications and captured logs.
- [ ] The runner cannot write outside the configured workspace through its own path handling.

**Verification:** Integration tests run fixture commands for success, failure, timeout, signal, output creation, and argument quoting.

**Dependencies:** Task 5.

### Checkpoint: adapter safety

- [ ] SQLite integration tests pass.
- [ ] Filesystem security tests pass.
- [ ] Subprocess tests prove `shell=False` behavior and timeout cleanup.

### Phase 3: Vertical CLI slices

#### Task 7: Validate, init, and plan commands

**Description:** Connect YAML parsing, validation, canonical planning, CLI rendering, JSON output, and starter runbook generation.

**Acceptance criteria:**

- [ ] `init`, `validate`, and `plan` work in a clean temporary directory.
- [ ] Human and JSON output expose stable codes, digests, dependencies, and order.
- [ ] Invalid input exits non-zero with an actionable message.

**Verification:** CLI integration tests execute installed commands through `subprocess`.

**Dependencies:** Tasks 2 and 3.

#### Task 8: Run, status, and inspect commands

**Description:** Implement the new-run lifecycle, sequential DAG execution, attempt persistence, logs, status projections, and inspection reports.

**Acceptance criteria:**

- [ ] A sample workflow completes and persists all expected evidence.
- [ ] A failing step blocks dependents and returns the documented exit code.
- [ ] `status` and `inspect` work after process restart and in JSON mode.

**Verification:** End-to-end CLI tests cover success, failure, blocked dependencies, repeated runs, and interrupted attempts.

**Dependencies:** Tasks 4, 5, 6, and 7.

#### Task 9: Repair and resume commands

**Description:** Implement repair-plan generation, plan identity/freshness checks, confirmation gates, safe retry selection, and resume execution.

**Acceptance criteria:**

- [ ] `repair` never executes a command.
- [ ] Changing a runbook, input, output, dependency, or policy invalidates the correct step closure.
- [ ] `resume` rejects stale plans and unsafe side effects without explicit confirmation.

**Verification:** End-to-end tests cover transient retry, changed input, missing output, side-effect confirmation, stale plan, and dependent invalidation.

**Dependencies:** Tasks 3, 4, 5, 6, and 8.

### Checkpoint: MVP user journey

- [ ] A clean environment can run init → validate → plan → run → inspect → repair → resume.
- [ ] Sample data demonstrates one success, one failure, and one safe recovery.
- [ ] Exit codes and JSON output are stable and documented.

### Phase 4: Hardening and release readiness

#### Task 10: Exporters, docs, examples, and benchmarks

**Description:** Add canonical JSON export, human reports, example runbooks, architecture references, CLI documentation, and focused performance benchmarks.

**Acceptance criteria:**

- [ ] Exported evidence is deterministic and redacted.
- [ ] Examples work without external services or secrets.
- [ ] Benchmarks report measured planning, hashing, persistence, and execution overhead.

**Verification:** Documentation commands are executed in a clean environment and benchmark output is committed as a methodology/result summary, not an unsupported claim.

**Dependencies:** Task 9.

#### Task 11: Security, static checks, and CI

**Description:** Add formatting/lint/type checks, unit/integration/e2e test jobs, coverage, dependency audit, secret scan, package build, and a Docker smoke test if the environment supports it.

**Acceptance criteria:**

- [ ] CI fails on test, lint, type, build, or security-check regressions.
- [ ] No secrets, raw environment values, or generated state databases are tracked.
- [ ] The package builds from a clean checkout.

**Verification:** Run all local CI-equivalent commands and inspect the GitHub Actions workflow after push.

**Dependencies:** Task 10.

#### Task 12: Open-source governance and release packaging

**Description:** Add README, LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CHANGELOG, issue templates, PR template, version metadata, release notes, and a clean commit history.

**Acceptance criteria:**

- [ ] A new contributor can install, run the example, understand the architecture, and file a security report.
- [ ] All public commands and schema compatibility rules are documented.
- [ ] A tagged release is possible only after verification evidence is captured.

**Verification:** Perform a documentation link check, clean-clone installation test, and final maintainer/recruiter review.

**Dependencies:** Task 11.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Scope expands into a workflow platform | High | Keep sequential local MVP and enforce explicit non-goals. |
| Resume semantics are unsafe | High | Make side-effect class and confirmation gates mandatory; test stale plans and invalidation closures. |
| Fingerprinting creates false confidence | High | Use explicit language that fingerprints are observations, not proof of reproducibility; expose external-state limitations. |
| SQLite state becomes a hidden source of truth | Medium | Store canonical attempt evidence and make copied run bundles inspectable; keep schema versioned. |
| YAML is difficult to evolve | Medium | Version the schema, reject unknown fields in MVP, and add additive migration rules later. |
| CLI UX is too complex | Medium | Keep the first path to five commands and use actionable errors with stable JSON output. |
| New name conflicts with an existing project | Low | Recheck GitHub/package registries before repository creation and be prepared to rename before publication. |

## Definition of done

The MVP is complete only when the clean-clone quick start works, the failure-and-repair scenario is reproducible, all documented tests and checks run, security-sensitive behavior is covered, CI is configured, governance files exist, and no completion claim is made without recorded evidence.
