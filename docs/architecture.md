# Architecture

The Evil Repository has four execution planes.

## Control plane

The React application reads normalized JSON and server-sent events from
FastAPI. It can create model profiles and runs, inspect scores, and render the
hypothesis/evidence graph. It does not load scenario Python or talk to Docker.
The Web container is the single deployment entrypoint and proxies `/api/v1`
to FastAPI over the private control network.

FastAPI persists model profiles, queued runs, append-only events, hypotheses,
evidence, graph edges, scorecards, and artifact metadata in the platform
PostgreSQL database. Provider keys are encrypted before storage. Application
accounts use one unique account name, with no email dependency. HttpOnly
sessions, per-session CSRF tokens, role checks, and access-mapping tables
protect tenant-scoped model profiles and runs. The administrator surface also
owns registration policy, account controls, and aggregate service telemetry.

The Compose control network is an ordinary private bridge so Rootless Docker
can publish the loopback-only API/UI ports. Platform PostgreSQL has no published
port. This bridge is not a candidate boundary; candidates always use Docker
network mode `none`.

## Runner plane

The worker claims queued runs, invokes the Scenario SDK lifecycle, calls the
selected model provider, validates normalized tool requests, and relays them to
one ephemeral candidate container. It is the only service with access to the
Rootless Docker socket.

The trusted Runner process uses UID 0 inside its control container because a
Rootless Docker socket bind mount maps its host owner to container root. That
UID is namespaced by the host's Rootless daemon; it does not make the host
daemon rootful. Candidate containers remain fixed at unprivileged UID 1000.

Model inference happens outside the candidate container. Provider credentials
are never copied into a scenario workspace or sandbox environment.

## Candidate plane

Each run gets a new container with:

- Docker network mode `none`;
- a read-only root filesystem;
- a per-run, size-bounded tmpfs Docker volume mounted at `/workspace`;
- all Linux capabilities dropped;
- `no-new-privileges`;
- process, memory, CPU, tool-output, and time limits;
- no Docker socket, provider key, or host bind mount.

The Runner fills the tmpfs volume through a short-lived, networkless trusted
staging container, then starts the read-only candidate container with that
volume. This avoids weakening the candidate root filesystem for archive import.
The candidate can act only through project tools; Docker operations remain an
implementation detail of the trusted Runner.

The canonical sandbox starts an in-container PostgreSQL instance on a Unix
socket and exposes a dirty SQLite file. This database is scenario data, not the
platform database.

## Judge plane

Trusted host-side grading receives the patch and recorded telemetry. Static,
regression, mutation, golden-replay, resource, and security checks run outside
the model's tool surface. Only normalized outcomes become public run data.

Run archives contain replay metadata, patch/report artifacts, event data, and
hashes. They must never contain API keys, hidden fixtures, or control-plane
credentials.

## Data flow

```text
React → FastAPI → platform PostgreSQL
                  ↓ queued run
              Runner worker → model provider
                  ↓ validated tool call
              Rootless Docker → networkless candidate
                  ↓ patch + report + telemetry
              hidden judge → scorecard + archive
```

The detailed normative design is [`../DESIGN.md`](../DESIGN.md). Security
assumptions are in [`threat-model.md`](threat-model.md).
