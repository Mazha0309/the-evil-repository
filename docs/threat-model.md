# Threat Model

## Assets

The system protects:

- host files and processes;
- the Rootless Docker control socket;
- model-provider credentials;
- user password hashes, sessions, and account metadata;
- the platform PostgreSQL database;
- hidden grader code, fixtures, and truth models;
- artifacts and telemetry belonging to other runs;
- benchmark integrity and reproducibility.

## Adversaries

Candidate-generated commands and patches are untrusted. Scenario content can
contain prompt injection and malformed files. A model provider can return
malformed tool calls. A locally installed third-party scenario may contain
host-side Python and is therefore trusted code, not sandboxed data.

The default deployment does not attempt to defend against a malicious machine
administrator or a compromised kernel.

## Trust boundaries

1. The Browser crosses from a trusted host-side mirror into a candidate file.
2. Tool arguments cross from a model response into the Runner.
3. A prepared workspace archive crosses into the candidate container.
4. Diffs, reports, stats, and events cross back into grading and archival.
5. Provider requests cross the local machine's network boundary.
6. Scenario entrypoints execute in the trusted Runner process.
7. Browser requests and session cookies cross the public Web/API boundary.

Every crossing must validate structure, size, path, and allowed operation.
Candidate text is data even when it resembles an instruction.

## Existing controls

- Rootless Docker daemon rather than the system daemon.
- One ephemeral container per run.
- `network_mode=none`, read-only root, dropped capabilities, and
  `no-new-privileges`.
- No host workspace bind mount and no Docker socket inside candidates.
- Per-run tmpfs workspace volume and bounded resources.
- Relative-path validation and unsafe-symlink rejection before archive import.
- Tool allowlist, command-boundary policy, output caps, and hard run budgets.
- Provider credentials held only by the trusted Runner.
- Host-side hidden judge and artifact hashing.
- Loopback-bound UI/API defaults.
- HttpOnly expiring sessions, scrypt password hashing, per-session CSRF
  validation, account disablement, and role checks.
- A single normalized account name for login and display; no email addresses
  are collected without an email-backed feature.
- Per-user access mappings for model profiles, runs, events, graphs, and
  reports.
- Deterministic fault scripts and append-only audit events.

## Residual risk

Containers share the host kernel. A kernel or runtime vulnerability may escape
Rootless Docker. Rootless mode reduces impact but does not make arbitrary code
safe in an absolute sense.

The Runner owns a Docker socket and executes trusted scenario Python; compromise
of either is high impact. A third-party Scenario SDK package must receive the
same review as application code.

Provider endpoints can observe prompts and selected tool output. Do not use
private repositories or real incident data. Application authentication does
not replace TLS; an external deployment must use the operator's reverse proxy
or load balancer and secure session cookies.

Resource limits reduce denial-of-service risk but cannot eliminate disk,
kernel, daemon, or provider-level exhaustion. The offline Browser prevents live
network access; it does not make mirrored text trustworthy.

## Safer operation

- Use a dedicated non-production Linux user and workstation or VM.
- Keep the Rootless daemon and host kernel patched.
- Run only reviewed scenario entrypoints.
- Keep API/UI on loopback unless external access is required.
- Set `SETUP_TOKEN` before exposing an uninitialized instance.
- Terminate TLS in a reviewed operator-managed reverse proxy and set
  `SESSION_COOKIE_SECURE=true`.
- Use restricted, revocable provider keys and rotate them after a suspected
  compromise.
- Delete run volumes after handling sensitive experimental output.
- Stop all runs before changing the sandbox image or Docker context.

## Explicitly out of scope

- malicious host administrators;
- physical access;
- undisclosed kernel zero-days;
- real internet browsing from candidate containers;
- hostile public multi-tenant execution without an additional VM/microVM
  boundary, quotas, and tenant-isolated artifact storage.
