## Summary

Describe the user problem and the change in one or two paragraphs.

## Safety and contract impact

Explain whether this changes command execution, path handling, environment handling, retry semantics, state transitions, reason codes, runbook schema, or JSON output. If it does not, say why.

## Verification

- [ ] `ruff format --check src tests`
- [ ] `ruff check src tests`
- [ ] `mypy src`
- [ ] `pytest -q`
- [ ] `python -m build --wheel --sdist --outdir dist`

## Documentation

- [ ] README or relevant docs updated.
- [ ] New public behavior and compatibility impact documented.
- [ ] No generated state, secrets, or build artifacts are included.
