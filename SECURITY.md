# Security Policy

The Evil Repository executes adversarial, model-directed code. Security reports
are welcome and should be handled privately.

## Supported versions

Until the first stable release, only the current `main` branch receives
security fixes.

## Reporting a vulnerability

Use the repository's private GitHub Security Advisory form when available. Do
not open a public issue for a suspected sandbox escape, credential exposure,
archive traversal, command-policy bypass, cross-run data leak, or hidden-judge
disclosure.

Please include:

- affected commit and operating system;
- Rootless Docker and kernel versions;
- minimum reproduction;
- expected and observed boundary;
- whether provider credentials, host files, or another run were reachable;
- any temporary mitigation already tested.

Avoid accessing data beyond the minimum needed to demonstrate impact. We will
acknowledge a complete report, reproduce it, coordinate a fix and disclosure,
and credit the reporter if requested. This document does not promise a bounty.

## Operational warning

Run only synthetic or trusted scenarios. Keep the UI and API bound to loopback.
Use a dedicated Rootless Docker daemon and a non-production workstation. Never
put secrets in scenario content or candidate environment variables. The full
security model and residual risks are documented in
[`docs/threat-model.md`](docs/threat-model.md).
