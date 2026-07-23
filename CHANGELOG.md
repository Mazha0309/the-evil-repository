# Changelog

All notable platform changes are recorded here. The project follows Semantic
Versioning while individual benchmark scenarios retain independent versions.

## [0.8.1] - 2026-07-24

### Changed

- Model-profile deletion now performs a credential-destroying archive:
  encrypted API keys, endpoints, tool mode and inference parameters are
  cleared, while stable rows and historical run foreign keys remain.
- Missing non-secret candidate or judge identity snapshots are backfilled
  before archival so old run results remain attributable and replayable.
- Active runs serialize against profile changes and prevent deletion until
  they finish or are cancelled; archived profiles are excluded from model
  registries, run creation and dashboard counts.

### Fixed

- Replaced the foreign-key failure that made referenced model profiles
  impossible to delete.
- Added a bilingual destructive confirmation and visible active-run/error
  feedback to model deletion instead of failing behind a closed edit dialog.

## [0.8.0] - 2026-07-23

### Added

- A versioned Benchmark Suite contract with explicit scenario families,
  development/validation/held-out splits, immutable scenario references, and a
  machine-readable leaderboard-readiness policy.
- The initial Production Incident Engineering Suite 0.1.0. It honestly reports
  one active development family and is not leaderboard-eligible until it
  reaches five active families, three held-out families, and 20 scenario
  references.
- A private Truth Graph SDK with typed causal nodes and edges, multiple
  acceptable resolution paths, objective hidden checks, weighted causal
  coverage, partial credit, and strict reference validation.
- A generic Agent Graph schema and `/runs/{id}/agents` endpoint. Current
  built-in runs are explicitly single-Agent; spawn, delegation, roles,
  parent/child relationships, terminal states, and per-Agent usage are ready
  for external orchestrators without claiming an internal multi-Agent
  scheduler.
- Project-mediated deterministic observability tools for future scenarios:
  process listing, service status, journal queries, socket metadata, bounded
  process traces, and CPU profiles. They never inspect the host and are not
  retroactively enabled in Terminal Repository 3.0.3.
- Raw Provider-request budgets and telemetry, including retry attempts, plus
  optional paired Token budgets and a versioned resource-ledger artifact.

### Changed

- Repositioned the bilingual README, design specification, API description, and
  WebUI around realistic repository-scale production incident engineering
  instead of difficulty as a product claim.
- The Scenario page now shows Suite diversity and held-out readiness rather
  than implying that one public scenario is a statistically valid global
  leaderboard.
- Candidate events now carry a stable `candidate/root` identity, and archives
  include derived Agent Graph and resource-ledger artifacts.
- Run creation now freezes non-secret candidate and semantic-judge identity;
  run tables and detail/result headers show the candidate profile name while
  Provider model IDs remain available in audit data without exposing
  credentials or endpoints.
- Resource accounting deliberately does not estimate or rank dollar cost:
  cache reads/writes, hidden reasoning Tokens, batch/service tiers, discounts,
  and compatible-API usage semantics are not reliably comparable.
- Terminal Repository 3.0.3 recalibrates the active-time envelope from 40/80
  to 30/60 minutes after completed 3.0.2 runs clustered around 35–37 minutes.
  Wall time remains observed-only rather than a score input; `completed` means
  execution and grading ended, not that the incident was solved.
- Clarified that the 180-tick Incident Director horizon is logical replay time,
  while real execution uses a 30-minute soft threshold and 60-minute hard
  stop.

### Fixed

- Corrected the dashboard's stale hard-limit label to the calibrated `60m`.

## [0.7.1] - 2026-07-23

### Fixed

- Long semantic-judge evidence references now wrap within criterion and
  disputed-claim cards instead of overflowing the result layout.
- Soft tool/time budgets now emit a deterministic Runner warning instead of
  existing only as stored configuration.
- Provider HTTP 408/425/429 and common 5xx responses now use bounded,
  `Retry-After`-aware backoff with audited retry events instead of immediately
  failing the benchmark run.

### Changed

- Terminal Repository Scenario 3.0.2 recalibrates tool-call budgets from
  1,200/2,200 to 250/650 using a 35-minute, 443-call full-scale run while
  retaining the 40/80-minute time budgets.
- Tool-efficiency points now decline between the configured soft and hard
  call limits, and invalid soft/hard ordering is rejected.

## [0.7.0] - 2026-07-23

### Added

- Editable model profiles with preserve/replace/clear API-key semantics.
- A bilingual, Provider-aware inference parameter editor for temperature,
  top-p, maximum output tokens, reasoning/thinking effort, service tier, and
  bounded advanced JSON.
- An administrator-controlled 1–16 slot Runner pool, initialized by
  `RUNNER_CONCURRENCY`, dynamically applied without restarting or terminating
  active runs, with occupied/total slot telemetry in the monitor.
- A destructive cancellation confirmation showing the run and current stage
  before the non-resumable workspace and conversation cleanup begins.

### Changed

- OpenAI Responses, Anthropic Messages, compatible Chat Completions, and
  Ollama parameters now map to protocol-correct request fields.
- Model parameter validation rejects credentials, headers, prompts, tools,
  transport fields, oversized JSON, excessive nesting, and invalid common
  numeric ranges.
- Provider adapters protect canonical model, message/input, tools, tool choice,
  and stream values even when a legacy database profile contains conflicting
  keys.

### Fixed

- Cancelling now records a terminal timestamp, clears a pending pause, exits at
  safe Runner boundaries, and can no longer be overwritten by later scoring or
  completion.

## [0.6.0] - 2026-07-23

### Added

- A real optional LLM semantic-judge pass using the selected model profile
  after deterministic grading. It produces a separate 0–100 review across
  causal coherence, evidence grounding, hypothesis discipline, decision/risk
  reasoning and communication reproducibility.
- Strict structured-output validation, exact rubric keys and per-criterion
  maxima, audit-reference validation, one bounded repair attempt, candidate
  identity blinding, prompt-injection canary detection and reliability labels.
- Versioned semantic-judge input, raw output and normalized review artifacts,
  plus prompt digests, Provider/model identity, latency, token usage, attempts
  and append-only lifecycle events.
- A bilingual semantic-review panel showing the independent score, criterion
  rationales, cited evidence, strengths, weaknesses, disputed claims and
  explicit separation from the primary leaderboard.

### Changed

- Provider adapters omit empty tool declarations for text-only judge calls.
- A missing, disabled, unavailable or malformed semantic judge no longer fails
  an otherwise valid benchmark run; the deterministic 1,200-point score is
  archived unchanged with an explicit review failure.
- The run form now describes the judge accurately instead of presenting an
  inert or ambiguous “independent judge” option.
- Deployment and shutdown commands now fail closed while runs are queued or
  active. A deliberately forced Runner restart marks interrupted in-memory
  runs as non-resumable failures instead of leaving false-live records.
- Terminal Repository Scenario 3.0.1 aligns metadata, API, WebUI and Compose
  on a 40-minute soft threshold and an 80-minute hard stop.

## [0.5.0] - 2026-07-23

### Added

- Terminal Repository Scenario 3.0.0 with a deterministic 180-tick incident
  director, intermittent failure replay, SLO/error-budget state, snapshots,
  rollback, bounded production actions, eight independently judged ticket
  dispositions, and valid no-change outcomes.
- Seven jointly required opaque runtime-leaf regressions across 704 executable
  cells, 40 semantic custody checkpoints, seven objective reasoning gates, an
  inspect-only recovered binary, conflicting toolchains, damaged caches,
  permission traps, phantom performance/auth reports, dirty databases, and
  date/clock deception.
- Project-mediated incident tools for service observations, snapshots,
  mitigations, verification and decisions. Candidate containers still receive
  no host, Docker socket or network access.
- Live incident telemetry for logical time, SLO, error budget, risk, data
  integrity, alerts, decisions, actions and the baseline/canary/replay/soak
  verification sequence.
- Four deterministic incident phases with 140-tick minimum progress,
  cross-phase/service observation coverage, ordered verification intervals and
  successful canary/replay/soak completion requirements. Incident alerts now
  enter the replay over all four phases instead of appearing as one startup
  dump, and temporal evidence coverage is exposed in the behavior profile.
- Held-out per-run instance seeds for contamination-resistant comparisons.
  Seeds alter opaque paths, runtime cells, histories, corpus and replay state,
  remain reproducible in trusted archives, and are omitted from candidate
  workspace metadata.
- Explicit score deductions and error-atlas counters for blind writes,
  repeated edits, protected or phantom fixes, database mutation, permission or
  boundary probes, risky actions without snapshots, weak-authority trust,
  hard-coded truth, error swallowing and missing self-verification.

### Changed

- Replaced result-heavy scoring with a 1,200-point incident and behavior judge:
  functionality, stabilization, causal diagnosis, provenance, environment
  forensics, objective reasoning, decision quality, self-verification,
  security, resilience, patch scope, state management, report and efficiency.
- Security credit now requires actual adversarial exposure; elapsed wall time
  is observable but never rewarded. Mixed-use Browser documents now contain
  both useful evidence and malicious instructions, so safe utility and
  injection over-refusal are measurable. A correct patch without complete
  incident decisions or post-change replay/soak is hard-capped.
- Candidate defaults are constrained to 0.5 CPU and 256 MiB RAM. Faults remain
  seeded and scripted so every run is reproducible. The sandbox includes
  offline binary-forensics tools, and the full oracle/near-miss/database/binary
  smoke path now runs in CI.
- The score view now renders a concrete 0/300/600/900/1200 total scale and a
  deduction ledger; radar axes are normalized percentages.

## [0.4.0] - 2026-07-23

### Added

- A default live Agent monitor that distinguishes Provider wait, tool
  execution, result analysis, Scenario preparation, and hidden judging.
- Current tool arguments, bounded result previews, Provider/tool latency,
  visible model output, active hypotheses, budget burn, completion progress,
  source/action coverage, and stall warnings.
- Adversarial-exposure telemetry for Browser searches and poisoned results,
  Issue/README access, scripted faults, boundary attempts, and prompt-injection
  canary echoes.
- Cooperative pause and resume controls that stop at the next Provider/tool
  boundary, preserve the candidate workspace and conversation, remain
  cancellable, and exclude paused time from the hard execution budget.

### Changed

- Run events now record `model.request`, Provider latency, and per-tool
  duration, without claiming access to private model chain-of-thought.
- The Web console fetches append-only event deltas every second instead of
  repeatedly downloading the complete audit stream.

## [0.3.0] - 2026-07-23

### Added

- Terminal Repository Scenario 2.0.0 with 192 executable projection shards,
  48 executable query fragments, 224 six-part conflict bundles, and deeply
  conflicting target-path history.
- Deterministic completion contracts, early-Final rejection, multi-source
  provenance gates, and a dirty-runtime contract phase in the hidden judge.
- Behavior profiles, an error atlas, and completion status in the run UI.
- Seven prompt-injection classes with explicit canary auditing.

### Changed

- Reworked the 1,200-point judge so an incorrect patch is capped at 300 and
  unproven short-circuit answers no longer receive default security/efficiency
  credit.
- Raised canonical soft/hard budgets for the evidence-heavy Scenario and made
  run overrides effective in the Runner.
- Canonical Scenario seeding now disables superseded versions while preserving
  historical runs.

### Fixed

- Fixed the blank 1,200-point radar by passing the registered ECharts core
  instance and sanitizing malformed score axes.
- Fixed Git ownership checks inside candidate workspaces and hidden grading.
- Updated the GitHub API job to the published `setup-uv@v9.0.0` action after
  the removed `v8` reference prevented the job from starting.

## [0.2.2] - 2026-07-23

### Fixed

- Aligned `AgentEngine.run()` with the Scenario SDK executor contract so a
  benchmark run no longer fails immediately with an extra positional argument.

## [0.2.1] - 2026-07-23

### Changed

- Reduced the minimum account password length from 12 to 8 characters.
  Passwords remain scrypt-hashed, and login attempts remain rate-limited.

## [0.2.0] - 2026-07-23

### Added

- Simplified Chinese documentation and a bilingual WebUI.
- OpenAI Responses and Anthropic Messages provider adapters.
- First-run administrator setup, account registration, login sessions, CSRF
  protection, and `admin` / `user` roles.
- Per-user isolation for model profiles, runs, event streams, graphs, and
  reports.
- Administrator user management and a live control-plane, Runner, database,
  queue, and Rootless Docker monitoring dashboard.
- Administrator-controlled public registration switch.

### Changed

- Accounts now use one unique account name for both login and display; no email
  address or separate display name is collected.
- Provider Base URL examples are placeholders and are never silently saved as
  configuration values.
- Platform version is now exposed by the API and displayed in the WebUI.

## [0.1.0] - 2026-07-23

### Added

- Initial EvilBench control plane, Scenario SDK, Rootless Docker runner,
  canonical terminal-repository scenario, scoring, audit stream, and React
  visualization console.
