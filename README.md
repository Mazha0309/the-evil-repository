# The Evil Repository

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

This repository is under active construction. The first release targets one
canonical “terminal repository” challenge and the complete execution,
telemetry, scoring, and visualization path around it.

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

The UI and API bind to loopback by default. Do not expose a development
deployment to an untrusted network.

## Repository layout

```text
apps/web/                  React/TypeScript control plane
apps/api/                  FastAPI API, worker, runner, scorer
scenarios/                 Versioned Scenario SDK packages and synthetic corpus
infra/sandbox/             Networkless candidate image
docs/                      Architecture, threat model, and authoring docs
```

The open design specification lives in [`DESIGN.md`](DESIGN.md). It is part of
the project—not an internal planning artifact. Architecture changes are
expected to update it in the same pull request.

Further reading:

- [`docs/architecture.md`](docs/architecture.md) — implementation map and trust boundaries
- [`docs/scenario-authoring.md`](docs/scenario-authoring.md) — build a Scenario SDK package
- [`docs/threat-model.md`](docs/threat-model.md) — security assumptions and residual risk
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — local setup and contribution rules
- [`SECURITY.md`](SECURITY.md) — responsible disclosure

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
