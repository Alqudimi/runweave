"""pytest configuration shared by the test suite.

RunWeave's CLI tests invoke the module through `python -m runweave`
subprocesses. By default `pytest-cov` only measures the pytest process,
so CLI coverage would stay artificially low. This plugin promotes the
active coverage collector to multiprocessing concurrency before the test
session starts, which hands the collector to every child process spawned
during tests so that the CLI emitter, error branches, and subcommand
paths are all measured by the same collector the suite already uses.
"""

from __future__ import annotations

from pathlib import Path


def pytest_configure(config: object) -> None:
    cov_plugin = config.pluginmanager.get_plugin("_cov")
    if cov_plugin is None:  # pragma: no cover
        return
    options = cov_plugin.options
    options.concurrency = ("multiprocessing",)
    options.parallel = True
    # Point both the main collector and every subprocess at the same
    # data file at the repository root so CLI invocations are measured
    # and merged with the pytest process data automatically.
    options.cov_data_file = str(Path.cwd() / ".coverage")
