# RunWeave Product Specification

## Product vision

RunWeave makes multi-step repository workflows safer to execute and easier to recover. It wraps commands that already exist in a project, records the state and contracts of each step, and produces an explicit repair plan when a run fails. The product is designed for local development, research scripts, release preparation, and CI jobs that are too important to rerun blindly but too small to justify a workflow platform.

> **Safe, resumable runbooks for the commands you already trust.**

## Problem statement

A repository workflow often spans dependency installation, data preparation, generation, tests, packaging, and publishing. When one step fails, developers typically inspect logs manually and rerun a large portion of the workflow. Timestamp-based task runners can skip work, and workflow platforms can persist execution state, but neither approach alone makes the safety decision visible for side-effecting commands. A stale output, changed runbook, modified input, or partially completed external action can make an apparently simple resume unsafe.

RunWeave treats recovery as a first-class product operation. It records enough local state to answer five questions before resuming: what definition was executed; what inputs and outputs were observed; which dependencies were satisfied; which failure class occurred; and which steps are safe, invalidated, blocked, or require confirmation.

## Target users

The primary users are solo developers, open-source maintainers, research engineers, ML engineers, and small platform teams who maintain repository workflows made of scripts, shell commands, data transformations, tests, and release steps. The initial user does not want to operate a scheduler or rewrite working code into a framework; they want a version-controlled runbook that remains inspectable on a laptop and can later be invoked in CI.

## Core use cases

| Use case | User outcome |
|---|---|
| Repeated local pipeline | Run a multi-step process while reusing valid completed work. |
| Failed data or build workflow | Inspect the failure and generate a repair plan without immediately executing anything. |
| Safe resume | Resume only steps whose contract and retry policy permit reuse or retry. |
| Release preparation | Mark packaging, signing, publishing, or deployment steps as side-effecting and require confirmation. |
| CI integration | Invoke the same runbook in CI and export machine-readable status and evidence. |
| Debugging | Inspect step logs, inputs, outputs, fingerprints, transitions, and reasons for invalidation. |
| Contribution | Add a provider or exporter without changing the domain model. |

## User stories

1. As a developer, I can describe a workflow in a committed YAML file and validate it before execution.
2. As a developer, I can see the dependency-aware plan before any command runs.
3. As a developer, I can execute a ready step without shell interpolation and capture structured stdout, stderr, exit code, duration, and termination reason.
4. As a developer, I can inspect a failed run and understand why each later step is blocked.
5. As a developer, I can generate a non-executing repair plan that explains reusable, invalidated, retryable, blocked, and confirmation-required steps.
6. As a developer, I can resume a run only when the repair plan still matches the current runbook and input state.
7. As a maintainer, I can declare that a step is idempotent, retryable, destructive, external, or manual so the engine does not infer unsafe behavior.
8. As a CI system, I can consume stable JSON output and a non-zero exit code when a run cannot safely complete.
9. As a contributor, I can add an exporter or state backend behind a documented interface.

## Functional requirements

### Runbook definition

The runbook is YAML with a schema version and a list of uniquely identified steps. Each step contains a command vector, optional working directory, explicit dependency IDs, declared input paths, declared output paths, environment variable names to pass through, timeout, retry policy, side-effect class, and evidence policy. A command is always represented as an argument vector; the MVP does not invoke a shell by default.

### Validation and planning

Validation rejects duplicate IDs, unknown dependencies, dependency cycles, invalid paths, unsupported retry policies, unsafe environment declarations, malformed command vectors, and output paths that escape the runbook root. Planning produces a deterministic topological order, identifies parallel-ready steps, and emits a stable plan digest.

### Execution and persistence

The engine persists run and step state in SQLite. State transitions are append-only in an event table and materialized into current run/step tables. A step may move through `PENDING`, `READY`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `BLOCKED`, `INVALIDATED`, or `REQUIRES_CONFIRMATION`. Transitions are validated by the domain layer and committed transactionally.

### Contract evaluation

For each step, RunWeave fingerprints declared inputs before execution and declared outputs after execution. The fingerprint includes path type, size, modification metadata, and a streaming SHA-256 digest for files; directory fingerprints are deterministic sorted-tree digests. The runbook digest, command digest, policy digest, and input digest are stored with the step attempt. The engine does not capture the entire filesystem and does not claim that an external API, clock, network service, or mutable container is reproducible unless explicitly declared by the user.

### Recovery and repair

The repair evaluator compares the current runbook and filesystem observations with the stored run. It returns a reason code and explanation for every step. Reusable steps require a matching runbook/command/policy digest, successful prior state, valid outputs, and unchanged declared inputs. Failed steps are retryable only when the error and step policy permit it. Side-effecting steps are confirmation-gated by default. Any change in a step invalidates dependent steps unless their contracts explicitly permit reuse.

### Evidence and export

Every completed or failed attempt produces a canonical JSON record containing run ID, step ID, attempt number, timestamps, command vector, working directory, declared inputs and outputs, fingerprints, exit status, policy, and redacted environment metadata. The MVP exports JSON and a human-readable report. The exporter interface leaves room for OpenLineage-style events and ReproLedger integration without making either dependency mandatory.

### CLI

The CLI uses stable machine-readable output via `--json` and clear human output by default. The initial commands are:

| Command | Purpose |
|---|---|
| `runweave init` | Create a starter runbook and state directory. |
| `runweave validate RUNBOOK` | Validate schema, paths, dependencies, and policy. |
| `runweave plan RUNBOOK` | Show deterministic execution order and ready steps. |
| `runweave run RUNBOOK` | Execute a new run. |
| `runweave status RUN_ID` | Show current run and step states. |
| `runweave inspect RUN_ID` | Show attempts, logs, fingerprints, and transition history. |
| `runweave repair RUN_ID` | Produce a non-executing repair plan. |
| `runweave resume RUN_ID --plan PLAN_ID` | Apply a still-valid repair plan under policy checks. |
| `runweave export RUN_ID --format json` | Export canonical evidence. |

## Non-functional requirements

| Requirement | MVP target |
|---|---|
| Safety | Never pass a command through a shell unless an explicit future adapter opts in; reject unsafe paths and redact sensitive environment names. |
| Determinism | Stable schema serialization, plan digest, topological ordering, fingerprint ordering, and reason codes. |
| Recoverability | A process crash cannot leave a step permanently in an ambiguous state; stale `RUNNING` attempts are detected and classified. |
| Portability | Python 3.11+, SQLite, and standard filesystem operations; no service required. |
| Observability | Structured logs, attempt records, transition history, and JSON export. |
| Extensibility | Domain model independent of CLI, SQLite, and exporters; provider interfaces are additive. |
| Performance | Stream file hashing in bounded chunks; avoid hashing undeclared paths; support parallel-ready planning before parallel execution is enabled. |
| Security | No secrets in runbooks or artifacts by default; environment allowlist; safe path resolution; bounded log capture; configurable output redaction. |
| Usability | A sample runbook can validate and execute in under five minutes on a clean Python environment. |

## Advanced features

After the MVP, the project can add a bounded parallel executor, remote state backends, Git metadata capture, CI adapters, OpenLineage exporter, DVC-aware input providers, signed attestations, content-addressed artifact storage, a read-only web viewer, and policy packs for release or deployment workflows. Each feature must preserve the local file-backed core and its explicit safety semantics.

## Future roadmap

The roadmap is staged around trust. Version 0.1 establishes local execution and recoverable state. Version 0.2 adds provider and exporter interfaces plus CI output. Version 0.3 adds policy packs and bounded parallelism. Version 0.4 adds remote read-only evidence and optional signed attestations. A future 1.0 release requires a stable schema compatibility policy, migration tooling, documented security review, and repeated clean-environment validation.
