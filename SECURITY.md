# Security Policy

## Scope

RunWeave executes user-authored commands and records local workflow evidence. Security reports are especially valuable when they demonstrate command injection, shell-boundary bypass, path traversal, symlink escape, secret persistence, log leakage, state corruption, or unsafe side-effect retries.

RunWeave is not a sandbox. A user should not execute an untrusted runbook on a host containing sensitive files. Use a container, VM, or other appropriate isolation boundary for untrusted workloads.

## Reporting a vulnerability

Please report vulnerabilities privately to the repository maintainer before opening a public issue. Include a clear description, affected version or commit, reproducible steps, expected and observed behavior, impact assessment, and any safe proof-of-concept. Do not include real credentials, private source code, or personal data.

The maintainer will acknowledge a report as soon as practical, investigate the reproduction, and coordinate a fix or mitigation. Public disclosure should wait until users have a reasonable opportunity to update. If private GitHub security advisories are enabled for the repository, prefer that channel.

## Security design commitments

The default executor uses argument vectors and `shell=False`. Declared paths are resolved beneath the runbook root, symlinks are rejected by default, logs are bounded, environment values are not persisted by default, and secret-looking environment names are redacted in evidence. External and destructive side effects require explicit policy and confirmation during recovery.

These controls reduce risk but do not replace host isolation, least privilege, network policy, or ordinary secure software practices.
