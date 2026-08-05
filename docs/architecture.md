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
scenario slug/version pairs and reports actual family, split, scenario, and
configured-instance coverage. React also displays the explicit publication
status and note; it does not infer maturity from an arbitrary scenario quota.

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
Codex CLI `auth.json`, Claude Code setup tokens, OAuth refresh, status
transitions, and destructive credential deletion remain control-plane
operations. Antigravity is represented in PostgreSQL only by a non-secret
deployment-session reference; the official CLI account state remains in the
`antigravity-data` named volume. Structured inference controls are mapped per
protocol, while bounded advanced JSON cannot override credentials, prompts,
messages, models, tools, or transport-owned fields.

The seven Provider adapters are OpenAI Responses, Anthropic Messages / the
official Claude Agent SDK, Codex subscription Responses, the official
Antigravity CLI, Gemini native `generateContent`, OpenAI-compatible Chat
Completions, and Ollama Chat. OAuth egress is not configurable: the Claude
setup token is consumed only by a tool-less official SDK subprocess with an
ephemeral config directory, Codex is pinned to OpenAI authentication and the
official Codex backend, and Antigravity traffic is owned only by the pinned
official `agy` process. Native Gemini is API-key only. API-key profiles may use
their explicit Base URL.

API and Runner mount the same persistent Antigravity home, but only the
unprivileged `evil` user can access it. The API executes `agy models` for
catalog checks; the Runner executes `agy --print` in an empty workspace with a
tool-less managed Agent, deny-all local permissions, and a minimal environment
that excludes Docker and control-plane secrets. The candidate container never
mounts this volume. CLI timeouts terminate the complete process group.

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
but intentionally does not estimate normalized dollar cost. Because `agy`
print mode exposes no machine-readable usage, Antigravity marks Token usage
unavailable and cannot select Token budgets; its other resource envelopes
remain observable and enforced.

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

Run archive schema v3 contains replay metadata, timestamped events,
patch/report artifacts, and a SHA-256 inventory. It additionally normalizes
Provider turns, tool call/result lifecycles, stage transitions, periodic
resource snapshots, budget adjustments, model turn boundaries, errors, and the
Hypothesis/Evidence graph into separate JSON/JSONL entries, and bundles the
final resource ledger together with a compact export payload. The full
directory contract is described under Archive contract below. The
authenticated report endpoint can produce the same detail from the live
database before terminal archival. Neither path may
contain API keys, OAuth tokens, hidden fixtures, thought signatures, or
control-plane credentials. Compose gives the Runner read/write access to the
host artifact directory and the API read-only access to that same directory;
database metadata alone is not considered proof that a downloadable file
exists.

### Archive contract

Run archives follow schema v3. The gzipped tarball contains:

- `run.json` — canonical manifest: scenario metadata, run context, result
  summary, telemetry summary, and artifact inventory, plus `integrity` roots
  (`events_sha256`, per-artifact `artifact_sha256`, and
  `detail_entry_sha256` for every telemetry and derived entry);
- `events.jsonl` — the full timestamped, immutable event stream;
- `telemetry/*` — per-aspect JSON/JSONL entries: `summary.json`,
  `provider-turns.jsonl`, `tool-lifecycle.jsonl`, `stage-timeline.jsonl`,
  `resource-snapshots.jsonl`, `context-compactions.jsonl`,
  `finalization-nudges.jsonl`, `budget-adjustments.jsonl`,
  `turn-boundaries.jsonl`, and `errors.jsonl`;
- `resource-ledger.json` — final resource usage ledger separating logical
  model turns from raw Provider requests;
- `export.json` — the compact export payload itself, so a single file suffices
  for basic analysis;
- `report.html` — a self-contained offline HTML report rendering the
  scorecard, hypothesis graph, audit trail, diffs, and telemetry with zero
  external dependencies;
- `investigation/graph.json` — hypotheses, revisions, evidence, and edges;
- `artifacts/index.json` plus `artifacts/*` — candidate and judge outputs with
  their size and SHA-256 inventory.

`export.json` uses `export_schema_version: 3` and carries only summary data:
`platform_version`, the run context, scenario metadata, a result summary
(elapsed seconds, tool-call count, final-response length), the normalized
scorecard when available, `telemetry_summary`, `artifact_inventory`,
`budget_adjustment_count`, `turn_summary`, and `investigation_graph`. It never
contains event bodies or artifact contents; those remain in `events.jsonl` and
`artifacts/*`. The authenticated `GET /runs/{id}/export` endpoint serves the
same payload (compact events by default, `include=full-events` to inline event
bodies) or the raw archive tarball.

Budget adjustment is append-only control-plane state. Each
`POST /runs/{id}/budget` request validates the merged BudgetSpec against the
Scenario contract and appends one `budget_overrides` entry (`field`, `value`,
`reason`, `requested_by`, `requested_at`) to `benchmark_runs.config`. The
Runner polls the config at model-turn boundaries and applies pending entries
as a batch, re-validating the merged candidate through
`BudgetSpec.model_validate` before swapping the runtime budget; invalid or
unknown fields are skipped with a warning and no partial application occurs.
Every applied entry emits a `run.budget_adjusted` event that lands in
`telemetry/budget-adjustments.jsonl`.

Scoring compares final usage against the Scenario's default budget, not any
dynamically adjusted runtime budget. Each dimension over its default hard
limit (active time, tool calls, Provider requests, total tokens) contributes
`min(overrun_ratio, cap) × weight` to a linear score penalty — weights default
to 30/30/15/15 across the four dimensions and the cap defaults to 2.0, both
configurable through `overtime_penalty_weights` and `overtime_penalty_cap`.
The resulting `overtime_penalty` block records per-dimension usage, overrun,
and penalty plus the score before and after. A run is censored
(`outcome.censored`, stage "Budget exhausted") only when final usage exceeds
the default budget; adjusting the runtime budget therefore never changes
censor status by itself.

A terminal run may be soft-deleted by setting `benchmark_runs.archived_at`.
Normal list, detail, report, graph, event, dashboard, and administrator
aggregate queries exclude archived runs, while ownership and all dependent
evidence remain intact for administrative database recovery. Active runs must
be cancelled or finish before archival.

## Data flow

```text
React → FastAPI → platform PostgreSQL
                  ↓ queued run
              Runner worker → adapter / official agy → model provider
                  ↓ validated tool call
              Rootless Docker → networkless candidate
                  ↓ patch + report + telemetry
              hidden judge → scorecard + archive
```

The detailed normative design is [`../DESIGN.md`](../DESIGN.md). Security
assumptions are in [`threat-model.md`](threat-model.md).
