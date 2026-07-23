# The Evil Repository

[English](README.md) | [简体中文](README.zh-CN.md)

> An evidence-hostile, container-isolated benchmark for long-horizon AI software agents.

The Evil Repository drops a model into a deterministic but uncertain production
incident: two cross-referenced Git repositories, contradictory documentation,
broken CI oracles, intermittent service symptoms, phantom bugs, prompt
injection, scripted tool failures, a stale SQLite cache, and a production-style
PostgreSQL snapshot full of dirty data. The model must decide what is real,
what must not be changed, how to contain risk, and only then make the smallest
proven patch with an auditable evidence report.

It is closer to an AI Agent CTF, incident-response benchmark, and behavior
analysis platform than a conventional “fix this failing test” dataset. A run
produces not only a 1,200-point scorecard, but also a Hypothesis/Evidence/Truth
Graph, behavior profile, discrete error statistics, and a replay of the
investigation.

The product is a local-first React data console backed by FastAPI. Every
candidate/task pair receives a fresh Rootless Docker workspace. Candidate
containers have no network, no Docker socket, no host bind mounts, and no model
provider credentials.

## Status

The platform is currently **v0.6.0** and remains under active construction.
See [`CHANGELOG.md`](CHANGELOG.md). This release includes the canonical
“terminal repository” challenge, account isolation, administrator controls,
server monitoring, a live Agent activity console, and the complete execution,
telemetry, scoring, and visualization path around it.

Long investigations can be paused at a safe Provider/tool boundary and resumed
without discarding the candidate workspace or conversation. Paused time does
not consume the configured hard execution budget.

The control plane supports four explicit model protocols: OpenAI Responses,
Anthropic Messages, OpenAI-compatible Chat Completions, and Ollama Chat.
OpenAI-compatible and OpenAI Responses remain separate because their message,
tool-call, and usage contracts are not interchangeable.

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

The benchmark is split into two layers:

1. a versioned Scenario SDK package containing repositories, databases,
   injections, deterministic failures, offline Browser material, hidden truth,
   grading, and metadata;
2. a scenario-agnostic Runner that performs
   `load → prepare → run → grade → archive` and exposes only normalized results
   to React.

The canonical scenario deliberately prevents a one-file, one-test shortcut.
Its relevant regression is buried beneath substantial later Git history;
README, issues, comments, TODOs, logs, CI output, database descriptions, and
Browser results conflict with one another; the second repository and commit
history carry independent provenance; and the live PostgreSQL state disagrees
with a stale SQLite cache. The offline mirror is available only through
`browser.search`, `browser.open`, and `browser.find`, so a candidate cannot
bypass Browser behavior by scanning a copied mirror directory.

Scenario 3.0.0 makes the apparent bulk material. Five live relay chains contain
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

A candidate must build an observable investigation, not merely guess a patch.
Before a normal final answer is accepted, the Scenario completion gate requires
explicit hypotheses, a rejected hypothesis, linked evidence, Git archaeology,
PostgreSQL and SQLite forensics, offline Browser research, runtime
verification, and a substantive `INVESTIGATION.md`. The hidden judge then
validates the patch against fresh state, mutations, replay, security rules, and
the scenario's private Truth Graph. Satisfying the gate proves coverage, not
correctness.

The canonical completion contract has no minimum call-count padding. It
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

The canonical difficulty target is a reference solve of at least 80 minutes
for a strong software-engineering Agent. This is a calibration target, not a
wall-clock promise: EvilBench never pads a run with `sleep`, random delay, or
an 80-minute timer. Difficulty must come from necessary evidence work,
conflicting provenance, bounded recovery from scripted failures, and hidden
verification. Scenario releases are recalibrated when strong Agents discover
material shortcuts.

Use an optional held-out instance seed when comparing models. It changes the
opaque file layout, runtime cells, histories, corpus and incident replay while
remaining deterministic; the seed is archived for replay but is not copied
into the candidate workspace. Reuse the same seed across compared models.

Scenario maintainers can run the same oracle, near-miss, dirty-database,
binary-forensics and resource-envelope checks used by CI:

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

This stops and removes the application containers and Compose networks while
preserving the PostgreSQL data volume. Run `make deploy` again to resume with
the existing accounts, settings, and benchmark data.

## Repository layout

```text
apps/web/                  React/TypeScript control plane
apps/api/                  FastAPI API, worker, runner, scorer
scenarios/                 Versioned Scenario SDK packages, truth, and corpus
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
