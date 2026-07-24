# Architecture

The Evil Repository has four execution planes.

## Control plane

The React application reads normalized JSON and server-sent events from
FastAPI. It can create model profiles and runs, inspect scores, and render the
hypothesis/evidence graph. It does not load scenario Python or talk to Docker.
The Web container is the single deployment entrypoint and proxies `/api/v1`
to FastAPI over the private control network.

FastAPI persists model profiles, owner-scoped Provider credentials, queued
runs, append-only events, hypotheses, evidence, graph edges, scorecards, and
artifact metadata in the platform PostgreSQL database. API keys and imported
OAuth documents are encrypted before storage; only kind, status, expiry,
account hint, and references are serialized. Application accounts use one
unique account name, with no email dependency. HttpOnly
sessions, per-session CSRF tokens, role checks, and access-mapping tables
protect tenant-scoped model profiles and runs. The administrator surface also
owns registration policy, account controls, and aggregate service telemetry.

The Suite registry is file-backed and versioned independently from scenario
packages. `/api/v1/suites` validates family/split manifests against installed
scenario slug/version pairs and reports whether the declared diversity and
held-out thresholds are actually met. React displays that state; it does not
infer leaderboard readiness.

The Compose control network is an ordinary private bridge so Rootless Docker
can publish the loopback-only API/UI ports. Platform PostgreSQL has no published
port. This bridge is not a candidate boundary; candidates always use Docker
network mode `none`.

## Runner plane

The worker claims queued runs into a bounded in-process pool, invokes the
Scenario SDK lifecycle, calls each selected model provider, validates
normalized tool requests, and relays them to ephemeral candidate containers.
It is the only service with access to the Rootless Docker socket.

`RUNNER_CONCURRENCY` initializes a fresh database to two slots. Administrators
can change the 1–16 limit live; lowering it stops new claims but never kills
active work. Every concurrent run has a distinct container, tmpfs workspace,
Provider client, conversation, prepared private state, and archive. The
administrator monitor reads aggregate occupied/total slot counts from the
Runner heartbeat. The Runner service remains a singleton; operators tune its
pool instead of starting replicas with competing in-memory ownership.

The trusted Runner process uses UID 0 inside its control container because a
Rootless Docker socket bind mount maps its host owner to container root. That
UID is namespaced by the host's Rootless daemon; it does not make the host
daemon rootful. Candidate containers remain fixed at unprivileged UID 1000.

Model inference happens outside the candidate container. Provider credentials
are never copied into a scenario workspace or sandbox environment. Model
profiles reference reusable owner-scoped credentials. API keys, imported
Codex CLI `auth.json`, imported Gemini CLI `oauth_creds.json`, Claude Code
setup tokens, OAuth refresh, status transitions, and destructive credential
deletion remain control-plane operations. Structured inference controls are
mapped per protocol, while bounded advanced JSON cannot override credentials,
prompts, messages, models, tools, or transport-owned fields.

The six Provider adapters are OpenAI Responses, Anthropic Messages / the
official Claude Agent SDK, Codex subscription Responses, Gemini native
`generateContent`, OpenAI-compatible Chat Completions, and Ollama Chat. OAuth
egress is not configurable: the Claude setup token is consumed only by a
tool-less official SDK subprocess with an ephemeral config directory, Codex is
pinned to OpenAI authentication and the official Codex backend, and Gemini is
pinned to Google OAuth and Code Assist. API-key profiles may use their explicit
Base URL.

Deleting a profile archives its stable row instead of cascading through run
history. The control plane blocks deletion while a run is active, freezes any
missing historical model identity, detaches its reusable credential, erases
connection parameters, and excludes the archived profile from future
selection. Credential deletion is separate and blocked while referenced.

Candidate events carry stable Agent identities. The built-in executor currently
emits one `candidate/root` node; the derived Agent Graph schema also supports
spawn, delegation, parent/child roles, terminal states, and per-Agent usage for
external multi-Agent orchestrators. Semantic judges and hidden graders remain
outside the candidate graph.

The resource ledger separates logical model turns from raw Provider requests
and counts retry attempts. It preserves Provider-reported input/output Tokens
but intentionally does not estimate normalized dollar cost.

At safe model-turn boundaries, the Runner also evaluates the active-time,
tool-call, Provider-request, and optional Token envelopes. Crossing the later
of a soft threshold or 80% of its hard threshold emits one
`run.finalization_nudge` and appends a trusted convergence message with
remaining resources and completion gaps. Paused time is excluded and the
message cannot extend a budget or bypass the deterministic completion gate.

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

Run archive schema v2 contains replay metadata, timestamped events,
patch/report artifacts, and a SHA-256 inventory. It additionally normalizes
Provider turns, tool call/result lifecycles, stage transitions, periodic
resource snapshots, errors, and the Hypothesis/Evidence graph into separate
JSON/JSONL entries. The authenticated report endpoint can produce the same
detail from the live database before terminal archival. Neither path may
contain API keys, OAuth tokens, hidden fixtures, thought signatures, or
control-plane credentials. Compose gives the Runner read/write access to the
host artifact directory and the API read-only access to that same directory;
database metadata alone is not considered proof that a downloadable file
exists.

A terminal run may be soft-deleted by setting `benchmark_runs.archived_at`.
Normal list, detail, report, graph, event, dashboard, and administrator
aggregate queries exclude archived runs, while ownership and all dependent
evidence remain intact for administrative database recovery. Active runs must
be cancelled or finish before archival.

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
