# The Evil Repository

[English](README.md) | [简体中文](README.zh-CN.md)

> An evidence-hostile, container-isolated benchmark for long-horizon AI software agents.

The Evil Repository drops a model into a deliberately rotten software incident:
two cross-referenced Git repositories, contradictory documentation, broken CI
oracles, prompt injection, deterministic tool failures, a stale SQLite cache,
and a production-style PostgreSQL snapshot full of dirty data. The model must
find the real regression, make the smallest correct patch, and support it with
an auditable evidence report.

The product is a local-first React data console backed by FastAPI. Every
candidate/task pair receives a fresh Rootless Docker workspace. Candidate
containers have no network, no Docker socket, no host bind mounts, and no model
provider credentials.

## Status

The platform is currently **v0.2.1** and remains under active construction.
See [`CHANGELOG.md`](CHANGELOG.md). This release includes the canonical
“terminal repository” challenge, account isolation, administrator controls,
server monitoring, and the complete execution, telemetry, scoring, and
visualization path around it.

## Quick start

Requirements:

- Linux with Rootless Docker and Docker Compose
- Node.js 22+ and pnpm
- Python 3.12+ and uv

```bash
cp .env.example .env
# If your local uid is not 1000, update ROOTLESS_DOCKER_SOCKET in .env.
make preflight
make bootstrap
make sandbox
docker compose up --build
```

Then open `http://127.0.0.1:5173`.

On a fresh database, the first page creates the initial administrator. Set
`SETUP_TOKEN` before startup if anyone else could reach the service during
initialization. Public registration is disabled by default and can be switched
on or off immediately from the administrator console.

The UI and API bind to loopback by default. Do not expose a development
deployment to an untrusted network.

## Accounts and administration

Authentication is implemented by the application, not delegated to a reverse
proxy. It provides:

- first-run administrator setup and optional public registration;
- one unique account name for both sign-in and display, with no email-service
  dependency;
- 8-character minimum passwords, scrypt hashing, and login rate limiting;
- `admin` and `user` roles;
- HttpOnly session cookies, CSRF-protected mutations, session listing and
  revocation;
- per-user model-profile, run, event, graph, and report isolation;
- administrator account creation, enable/disable, role changes, and global
  session revocation;
- live API, Runner, PostgreSQL, queue, CPU, memory, disk, and Rootless Docker
  monitoring.

Administrators can see legacy and global benchmark data. Ordinary users see
only resources mapped to their account.

## External deployment

The project does not bundle Caddy, Nginx, Traefik, DNS, or certificate
management. The production Compose profile exposes one Web entrypoint and
proxies `/api/v1` internally; API, Runner, and PostgreSQL remain private.

```bash
cp .env.production.example .env.production
# Replace every CHANGE_ME value and set your public WEB_ORIGIN.
make deploy-public
```

Point your own reverse proxy at the configured `WEB_BIND_PORT`. When the public
origin uses HTTPS, keep `SESSION_COOKIE_SECURE=true`. `make deploy-public`
refuses placeholder secrets, a non-HTTPS origin, or insecure session cookies.
Do not expose a fresh installation without setting `SETUP_TOKEN`.

## Repository layout

```text
apps/web/                  React/TypeScript control plane
apps/api/                  FastAPI API, worker, runner, scorer
scenarios/                 Versioned Scenario SDK packages and synthetic corpus
infra/sandbox/             Networkless candidate image
docs/                      Architecture, threat model, and authoring docs
```

The open design specification lives in [`DESIGN.md`](DESIGN.md), with a
[Simplified Chinese edition](DESIGN.zh-CN.md). It is part of the project—not
an internal planning artifact. Architecture changes are expected to update
both editions in the same pull request.

Further reading:

- [`docs/architecture.md`](docs/architecture.md) — implementation map and trust boundaries
- [`docs/scenario-authoring.md`](docs/scenario-authoring.md) — build a Scenario SDK package
- [`docs/threat-model.md`](docs/threat-model.md) — security assumptions and residual risk
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — local setup and contribution rules
- [`SECURITY.md`](SECURITY.md) — responsible disclosure
- [`CHANGELOG.md`](CHANGELOG.md) — platform release history

## Safety model

Rootless Docker is a strong practical local boundary, not a mathematical
guarantee against every shared-kernel escape. The runner treats candidate code
as untrusted, never mounts the host workspace, and performs archive/path
validation when moving artifacts across the boundary. See
[`docs/threat-model.md`](docs/threat-model.md).

## License

Copyright © 2026 The Evil Repository contributors.

Licensed under the GNU Affero General Public License v3.0 only
(`AGPL-3.0-only`). Synthetic benchmark content distributed in this repository
is covered by the same license unless a file explicitly says otherwise.
