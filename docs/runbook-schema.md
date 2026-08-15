# RunWeave Runbook Schema

## Schema version

The MVP uses `schema_version: 1`. The schema is intentionally explicit: unknown keys are rejected so a typo cannot silently remove a safety policy. Future versions must be additive where possible and must include migration notes.

## Example

```yaml
schema_version: 1
name: sample-transform
root: .
state_dir: .runweave
steps:
  - id: prepare
    command: [python, scripts/prepare.py]
    inputs: [data/source.txt]
    outputs: [build/normalized.txt]
    side_effect: WORKSPACE_WRITE
    retry:
      mode: NEVER
    evidence: STANDARD

  - id: test
    command: [python, -m, pytest, -q]
    depends_on: [prepare]
    inputs: [src, tests, build/normalized.txt]
    outputs: []
    side_effect: PURE
    retry:
      mode: ONCE
      retryable_errors: [NON_ZERO_EXIT]
    evidence: STANDARD

  - id: publish
    command: [python, scripts/publish.py, build/normalized.txt]
    depends_on: [test]
    inputs: [build/normalized.txt]
    outputs: [release/published.marker]
    side_effect: EXTERNAL_WRITE
    retry:
      mode: NEVER
    evidence: REDACTED
    recovery:
      require_confirmation: true
```

## Field contract

| Field | Type | Required | Contract |
|---|---|---:|---|
| `schema_version` | integer | yes | Must equal the supported schema version. |
| `name` | string | yes | Human-readable runbook name; stable IDs must not depend on it. |
| `root` | path | no | Workspace root relative to the runbook file; defaults to the runbook directory. |
| `state_dir` | path | no | State directory relative to root; defaults to `.runweave`. |
| `steps` | list | yes | One or more unique step definitions. |
| `steps[].id` | string | yes | Lowercase stable identifier matching `[a-z0-9][a-z0-9_-]{0,63}`. |
| `steps[].command` | list[string] | yes | Non-empty argv vector; no shell string form in the MVP. |
| `steps[].depends_on` | list[string] | no | Existing step IDs; defaults to an empty list. |
| `steps[].working_dir` | path | no | Root-relative directory; defaults to root. |
| `steps[].inputs` | list[path] | no | Root-relative declared inputs; missing paths are an observation and may fail policy. |
| `steps[].outputs` | list[path] | no | Root-relative declared outputs expected after success. |
| `steps[].env` | list[string] | no | Environment variable names to pass through; values are never stored by default. |
| `steps[].timeout_seconds` | number | no | Positive bounded timeout; defaults to 3600. |
| `steps[].side_effect` | enum | no | `PURE`, `WORKSPACE_WRITE`, `NETWORK_READ`, `EXTERNAL_WRITE`, or `DESTRUCTIVE`; defaults to `PURE`. |
| `steps[].retry.mode` | enum | no | `NEVER`, `ONCE`, or `BOUNDED`; defaults to `NEVER`. |
| `steps[].retry.max_attempts` | integer | no | Required for `BOUNDED`; bounded to a safe maximum. |
| `steps[].retry.retryable_errors` | list[enum] | no | Failure classes eligible for automatic retry. |
| `steps[].evidence` | enum | no | `STANDARD` or `REDACTED`; controls report detail. |
| `steps[].recovery.require_confirmation` | boolean | no | Defaults to true for external/destructive side effects and false otherwise. |

## Stable status values

`PENDING`, `READY`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `BLOCKED`, `INVALIDATED`, and `REQUIRES_CONFIRMATION` are public values. They are serialized in uppercase and may be extended additively but not renamed in a compatible schema version.

## Stable decision values

Repair decisions are `REUSE`, `RETRY`, `RERUN`, `BLOCK`, `CONFIRM`, and `SKIP`. Every decision includes a reason code and a human explanation. The engine does not return a bare boolean such as “safe to resume.”

## Reason codes

| Code | Meaning |
|---|---|
| `SUCCESS_CONTRACT_MATCH` | Prior success and current contract/declared observations match. |
| `INPUT_CHANGED` | A declared input fingerprint changed. |
| `OUTPUT_MISSING` | A declared output is missing. |
| `OUTPUT_CHANGED` | A declared output differs from the recorded result. |
| `RUNBOOK_CHANGED` | The canonical runbook digest changed. |
| `COMMAND_CHANGED` | The command vector or working directory changed. |
| `POLICY_CHANGED` | Retry, side-effect, or evidence policy changed. |
| `DEPENDENCY_INVALIDATED` | A dependency cannot be reused safely. |
| `DEPENDENCY_FAILED` | A dependency failed and has no approved recovery decision. |
| `FAILURE_RETRYABLE` | The recorded failure class is allowed by policy. |
| `FAILURE_NOT_RETRYABLE` | The recorded failure class is not eligible for retry. |
| `SIDE_EFFECT_CONFIRMATION` | An external or destructive retry requires explicit confirmation. |
| `STALE_RUNNING_ATTEMPT` | A previous process ended while the step was running. |
| `PLAN_STALE` | The repair plan no longer matches the current runbook or observations. |

## JSON output contract

All machine-readable commands return an object with a `schema_version`, `ok`, and `command` field. Success responses include a `data` object. Failure responses include a structured `error` object with `code`, `message`, `details`, and an optional `suggested_action`.

```json
{
  "schema_version": 1,
  "ok": false,
  "command": "resume",
  "error": {
    "code": "SIDE_EFFECT_CONFIRMATION_REQUIRED",
    "message": "Step 'publish' is classified as EXTERNAL_WRITE and requires confirmation before retry.",
    "details": {"run_id": "run_01", "step_id": "publish"},
    "suggested_action": "Review the repair plan and pass --confirm-side-effects publish."
  }
}
```
