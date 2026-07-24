# The Evil Repository

[English](README.md) | [简体中文](README.zh-CN.md)

> An evidence-grounded, container-isolated benchmark for repository-scale AI
> software engineering and incident response.

The Evil Repository evaluates how an AI Agent investigates deterministic but
uncertain production failures at repository scale. Scenarios combine
cross-referenced Git histories, contradictory runtime or artifact evidence,
broken CI oracles, phantom reports, prompt injection, scripted tool failures,
and bounded production actions. The Agent must establish what is real,
preserve constraints, contain risk, and then make the smallest verified
recovery—which may deliberately contain no source-code change.

The project sits between a repository-scale software engineering benchmark, an
incident-response simulator, and an Agent behavior analysis platform. A run
produces not only a deterministic 1,200-point scenario scorecard, but also a
Hypothesis/Evidence graph, behavior profile, discrete error statistics,
resource ledger, Agent execution graph, and an investigation replay.

The product is a local-first React data console backed by FastAPI. Every
candidate/task pair receives a fresh Rootless Docker workspace. Candidate
containers have no network, no Docker socket, no host bind mounts, and no model
provider credentials.

## Status

The platform is currently **v0.10.0** and remains under active construction.
See [`CHANGELOG.md`](CHANGELOG.md). This release includes two independently
versioned scenarios, account isolation, administrator controls, server
monitoring, a live Agent activity console, and the complete execution,
telemetry, scoring, and visualization path around them.

This release also introduces the versioned Suite contract. The bundled
Production Incident Engineering Suite currently contains **two public
development scenarios in two active families**. Its policy requires at least 20
scenario references across five active families, including three held-out
families, before it may claim leaderboard readiness. The WebUI and `/suites`
API expose that readiness as `2/5`, `0/3`, and `2/20`; therefore the current
release is useful for detailed engineering analysis, but it is **not yet a
statistically valid general leaderboard**.

Long investigations can be paused at a safe Provider/tool boundary and resumed
without discarding the candidate workspace or conversation. Paused time does
not consume the configured hard execution budget. Pause state is held by the
live Runner process; it does not make a run safe to survive a Runner restart.

Malformed native tool arguments are quarantined rather than executed or treated
as an empty object. The whole mixed tool-call batch is rejected, an auditable
`provider.tool_call_invalid` event is recorded, and the model receives a clean
repair turn. Provider read/connect/protocol transport failures use bounded
backoff, and every HTTP attempt still consumes the configured raw Provider
request budget.

If an unexpected terminal exception occurs after Scenario preparation, the
Runner preserves a downloadable forensic checkpoint before removing the
container. It contains the event stream, repository diffs/status, bounded
investigation artifacts, scenario audit, resource ledger, and failure summary.
This checkpoint is replayable evidence, not a resumable model conversation.

The control plane supports four explicit model protocols: OpenAI Responses,
Anthropic Messages, OpenAI-compatible Chat Completions, and Ollama Chat.
OpenAI-compatible and OpenAI Responses remain separate because their message,
tool-call, and usage contracts are not interchangeable.

Model profiles can be edited after creation without re-entering a stored API
key. The bilingual parameter editor exposes temperature, top-p, maximum output
tokens, reasoning/thinking effort, and service tier using protocol-correct
field names. Additional Provider fields can be supplied as bounded JSON.
Credentials, headers, prompts, model IDs, tool declarations, and transport
fields are rejected from that JSON, and the Runner enforces the same boundary
again when constructing every request.

Deleting a model profile is a credential-destroying archive operation rather
than a cascading database delete. Its API key, endpoint, and inference
parameters are erased, while historical runs retain frozen non-secret model
identity and remain replayable. A profile referenced by an active run cannot
be deleted until that run finishes or is cancelled.

The Runner executes multiple independent runs concurrently. Two slots are
enabled by default; administrators can change the 1–16 slot limit live without
restarting or terminating active runs. `RUNNER_CONCURRENCY` sets the initial
value on a fresh database. Every slot still creates a separate UUID, container,
tmpfs workspace, conversation, fault state, and archive. The administrator
monitor reports occupied and total slots. Cancelling a run requires explicit
confirmation because its conversation and temporary workspace cannot be
resumed after cleanup.

Terminal run results can be soft-deleted with a separate confirmation.
Soft-deletion hides the run from lists, dashboards, score aggregates, detail
pages, and report endpoints without removing scores, events, graphs, artifacts,
ownership, or replay data. Active runs must first finish or be cancelled. The
retained row can be recovered administratively from the database; the current
release does not yet expose a restore UI.

An optional independent LLM semantic judge now performs a real second Provider
call after deterministic grading. It assigns a separate 0–100 review for
causal coherence, evidence grounding, hypothesis discipline, decision/risk
reasoning, and reproducible communication. This review never changes the
official 1,200-point score. The judge sees no candidate identity, must cite
versioned audit references, receives candidate text as explicitly untrusted
data, and may retry one malformed response. Provider or schema failure is
recorded without failing the benchmark run.

Selecting a semantic judge sends the bounded review packet to that model's
configured Provider from the control plane. Do not select an external Provider
for runs whose reports may contain data you are not permitted to disclose.

## Benchmark contract

The benchmark is split into three layers:

1. a versioned Suite manifest grouping independent scenario families and
   development, validation, and held-out splits;
2. a versioned Scenario SDK package containing repositories, databases,
   injections, deterministic failures, offline Browser material, hidden truth,
   grading, and metadata;
3. a scenario-agnostic Runner that performs
   `load → prepare → run → grade → archive` and exposes only normalized results
   to React.

Private truth is represented as a graph of causes, conditions, symptoms,
constraints, invariants, and remediations. A scenario may declare multiple
acceptable resolution paths—such as a verified forward fix or a safe
rollback—plus objective hidden checks. The evaluator reports partial causal
coverage without turning partial evidence into a false pass. Platform,
Suite, and Scenario versions are independent, so adding a new family never
silently changes a published scenario's truth.

## Included scenarios

- **[The Terminal Repository 3.0.4](scenarios/terminal-repository/DESIGN.md)** —
  a cross-repository protocol regression with a dirty database, polluted CI,
  intermittent runtime behavior, eight incident tickets, seven independent
  relay defects, and a 90/180-minute execution envelope.
- **[The Counterfeit Release 1.0.0](scenarios/counterfeit-release/DESIGN.md)** —
  a software-supply-chain recovery where clean source, Git tags, OCI artifacts,
  SBOM, provenance, signatures, transparency records, and deployed runtime
  disagree. It accepts either a verified rollback or an exact clean forward
  rebuild and uses a 60/120-minute execution envelope.

The Terminal Repository deliberately prevents a one-file, one-test shortcut.
Its relevant regression is buried beneath substantial later Git history;
README, issues, comments, TODOs, logs, CI output, database descriptions, and
Browser results conflict with one another; the second repository and commit
history carry independent provenance; and the live PostgreSQL state disagrees
with a stale SQLite cache. The offline mirror is available only through
`browser.search`, `browser.open`, and `browser.find`, so a candidate cannot
bypass Browser behavior by scanning a copied mirror directory.

Terminal Repository 3.0.4 makes the apparent bulk material. Five live relay chains contain
704 executable opaque cells; seven independent corruptions are jointly
required, and fixing six still fails. The two repositories contain exactly
5,000 tracked files and 2,000 commits, 40 semantic custody checkpoints, seven
objective reasoning gates, conflicting dependency eras, a recovered unknown
binary, damaged caches and approximately 100 MiB of offline material. Every
critical transition changes active behavior, and the named branches are
conflicting partial exports rather than golden snapshots.

A trusted, deterministic Incident Director adds eight live tickets: one real
intermittent regression, one correlated symptom, phantom performance and auth
reports, historical-only dirty data, environment drift, a permission trap, and
a genuine but out-of-incident 2038 risk. Production observations and actions
go through project-mediated tools. They advance a logical replay clock and
change SLO, error budget, data integrity, risk and rollback state without ever
exposing Docker or the host. “No change,” “preserve,” “reject,” and “defer” can
be correct answers.

Scenario authors can additionally expose deterministic, project-mediated
equivalents of `ps`, `systemctl`, `journalctl`, `lsof`/socket inspection,
`strace`, and `perf`. These tools observe only the simulated incident state;
they never attach to a host process or expose live packets. Their collectors,
clock domains, useful signals, and decoys remain replayable. Terminal
Repository 3.0.4 stays frozen and does not retroactively enable this new tool
pack.

A candidate must build an observable investigation, not merely guess a patch.
Before a normal final answer is accepted, the Scenario completion gate requires
explicit hypotheses, a rejected hypothesis, linked evidence, Git archaeology,
PostgreSQL and SQLite forensics, offline Browser research, runtime
verification, and a substantive `INVESTIGATION.md`. The hidden judge then
validates the patch against fresh state, mutations, replay, security rules, and
the scenario's private Truth Graph. Satisfying the gate proves coverage, not
correctness.

The Terminal Repository completion contract has no minimum call-count padding. It
requires 14 hypotheses including six rejected hypotheses, 60 evidence records,
Git/database/Browser/runtime/cross-repository/incident coverage, 40 distinct
service-signal-window observations across triage, containment, repair and
recovery, all eight services, dispositions for all eight tickets, at least 140
logical ticks, ordered successful canary/replay/soak verification after a
baseline, and a 6,500-character report. The judge separately deducts blind
edits, repeated work, phantom fixes, unsafe actions, permission or boundary
probes, database mutation, low-authority trust and missing post-change
verification.

Candidate sandboxes default to 0.5 CPU, 256 MiB RAM, 256 PIDs and a 1.5 GiB
ephemeral workspace. A one-sample quick check may lie; hidden grading reruns
static scope, regression, mutation, runtime and fresh-database golden replay.

The scenario difficulty target is to remain discriminating throughout a
long-running strong-Agent investigation. This is a calibration target, not a
wall-clock promise: EvilBench never pads a run with `sleep`, random delay, or
an artificial timer. Difficulty must come from necessary evidence work,
conflicting provenance, bounded recovery from scripted failures, and hidden
verification. Scenario releases are recalibrated when strong Agents discover
material shortcuts.

The incident's 180 ticks are deterministic logical replay steps, not 180
wall-clock minutes. Scenario 3.0.4 defaults to a 90-minute soft warning and a
180-minute hard observation envelope, with 600/2,200 tool calls and 300/720
raw Provider requests. The hard limit is a safety boundary, not an intended
duration or forced wait.

A hard-budget stop is now an explicit **right-censored outcome** rather than a
completed solution. Its partial score remains available for forensic analysis,
but it is labelled `budget_exhausted`, excluded from average-score and runtime
calibration aggregates, and must not establish a model's completion time.
Runtime calibration accepts only runs that avoid every hard limit, satisfy the
Scenario completion contract, pass hidden verification, and score at least
900/1,200. Older scorecards are classified from their archived
`hard_limits_crossed` ledger, so pre-3.0.4 truncated runs are not silently shown
as successes after an upgrade.

EvilBench records logical model turns, raw Provider HTTP requests (including
retries), input/output Token counts, tool calls, and active time. Optional
Token caps are supported, but dollar cost is deliberately not normalized:
cache reads/writes, hidden reasoning tokens, batch/service tiers, discounts,
and compatible-API usage semantics are not reliably comparable across
Providers.

Every candidate event carries a stable Agent identity. Today the built-in
executor is intentionally single-Agent and produces a one-node Agent Graph.
The event and archive schemas already support spawn, delegation, role,
parent/child, and per-Agent resource aggregation so external multi-Agent
orchestrators can integrate without redefining historical run data. The
platform does not pretend that a protocol-ready graph is a built-in
multi-Agent scheduler.

Use an optional held-out instance seed when comparing models. It changes the
opaque file layout, runtime cells, histories, corpus and incident replay while
remaining deterministic; the seed is archived for replay but is not copied
into the candidate workspace. Reuse the same seed across compared models.

Scenario maintainers can run the same oracle, near-miss, database,
binary/artifact-forensics and resource-envelope checks used by CI:

```bash
make scenario-validate
```

## Quick start

Requirements:

- Linux with Rootless Docker and Docker Compose
- GNU Make

```bash
cp .env.example .env
# If your local uid is not 1000, update ROOTLESS_DOCKER_SOCKET in .env.
make deploy
```

`make deploy` runs the Rootless Docker preflight, builds the isolated candidate
sandbox and application images, starts all services, and prints their status.
Then open `http://127.0.0.1:5173`.

`RUNNER_CONCURRENCY=2` initializes the setting on a fresh database. The
administrator console can change it later without a restart. Each active slot
can consume the configured per-sandbox CPU, memory and workspace limits and
can issue independent Provider requests, so reduce it on a small machine or
under a low API rate limit. HTTP 408/425/429 and common 5xx responses use
bounded `Retry-After`-aware backoff; read/connect/protocol transport failures
use the same bounded policy. A Provider that remains unavailable after the
retry budget still fails explicitly and leaves a downloadable forensic
checkpoint when Scenario preparation had completed.

Deployment and shutdown fail closed while any run is queued, preparing,
running, or scoring. Wait for those runs to finish or cancel them in the WebUI.
If interruption is intentional, `ALLOW_ACTIVE_RUN_DISRUPTION=1 make deploy`
overrides the guard; interrupted runs are marked failed on Runner startup
because their in-memory model conversations cannot be reconstructed.

Node.js 22+, pnpm, Python 3.12+, and uv are only required for host-side
development; the deployment command builds application dependencies inside
containers.

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

## Stop the deployment

```bash
make down
```

This refuses to stop while runs are queued or active. Once safe, it stops and
removes the application containers and Compose networks while preserving the
PostgreSQL data volume. Run `make deploy` again to resume with the existing
accounts, settings, and benchmark data. Use
`ALLOW_ACTIVE_RUN_DISRUPTION=1 make down` only to abandon active runs
deliberately.

## Repository layout

```text
apps/web/                  React/TypeScript control plane
apps/api/                  FastAPI API, worker, runner, scorer
suites/                    Versioned family/split manifests and readiness policy
scenarios/                 Versioned Scenario SDK packages, truth, and corpus
infra/sandbox/             Networkless candidate image
docs/                      Architecture, threat model, and authoring docs
```

The shared platform specification lives in [`DESIGN.md`](DESIGN.md), with a
[Simplified Chinese edition](DESIGN.zh-CN.md). Each scenario owns a separate
versioned design next to its implementation:

- [Terminal Repository design](scenarios/terminal-repository/DESIGN.md)
  ([简体中文](scenarios/terminal-repository/DESIGN.zh-CN.md))
- [Counterfeit Release design](scenarios/counterfeit-release/DESIGN.md)
  ([简体中文](scenarios/counterfeit-release/DESIGN.zh-CN.md))

These files are open project artifacts, not internal planning notes. Shared
architecture changes update both platform editions; scenario changes update
both editions in that scenario directory.

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
