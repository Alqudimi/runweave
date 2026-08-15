# RunWeave Verification Record

**Verification date:** 2026-08-15

## Results

| Check | Result | Evidence |
|---|---|---|
| Ruff formatting | Passed | `ruff format --check src tests` |
| Ruff lint | Passed | `ruff check src tests` |
| Strict mypy | Passed | `mypy src` reported no issues in 22 source files. |
| Automated tests | Passed | 19 tests passed across validation, fingerprints, subprocesses, SQLite/application services, recovery, and CLI end-to-end flows. |
| Test coverage | Passed as a monitored signal | 77% total line coverage from `pytest --cov=runweave`; the remaining gap is concentrated in CLI process-entry branches, unusual storage errors, and defensive parsing branches. |
| Wheel and sdist build | Passed | `runweave-0.1.0-py3-none-any.whl` and `runweave-0.1.0.tar.gz` built successfully. |
| Dependency audit | Passed with package caveat | `pip-audit` reported no known vulnerabilities in installed auditable dependencies and skipped the unpublished local `runweave` package because it is not on PyPI. |
| Manual smoke flow | Passed | `init → validate → plan → run → status` completed in a clean temporary directory. |
| Recovery flow | Passed | A retryable failure generated a repair plan, resumed successfully, and produced final `REUSE` decisions. |
| Safety gates | Passed | External-write recovery required confirmation; stale plans were rejected after a canonical runbook change. |

## Scope of evidence

The tests verify deterministic dependency planning, cycle and field validation, root and symlink safety, streamed file fingerprints, shell-free argument boundaries, non-zero and timeout classification, transactional run persistence, output validation, blocked dependencies, retryable recovery, side-effect confirmation, stale-plan rejection, JSON output, and the basic CLI journey.

The verification does not prove arbitrary command reproducibility, host isolation, external API idempotency, distributed execution, or correctness of user-authored commands. Those limitations are intentional and are stated in the product specification and security policy.

## Reproduction

From the repository root:

```bash
python -m pip install -e '.[dev]'
ruff format --check src tests
ruff check src tests
mypy src
pytest --cov=runweave --cov-report=term-missing -q
python -m build --wheel --sdist --outdir dist
pip-audit
```

For the manual path:

```bash
runweave init /tmp/runweave-demo.yml
runweave validate /tmp/runweave-demo.yml
runweave plan /tmp/runweave-demo.yml
runweave run /tmp/runweave-demo.yml
```
