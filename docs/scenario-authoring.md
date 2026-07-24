# Scenario Authoring

A scenario is a versioned directory package. React never interprets its
contents; the trusted Runner loads it through the Scenario SDK.

Scenarios are referenced by a separate `suites/<slug>/suite.yaml` manifest.
Assign a new scenario to an independent causal/task family and one of the
`development`, `validation`, or `held_out` splits. A different seed or file
layout of the same causal task is still the same family.

## Required layout

```text
scenarios/example/
├── DESIGN.md
├── DESIGN.zh-CN.md
├── metadata.yaml
├── scenario.py
├── generator.py                         # optional
├── repos/repositories.yaml
├── database/{init,dirty,hidden}.sql      # optional
├── injections/                          # optional
├── failures/
├── grading/{public.yaml,hidden.py,replay.py}
└── mirror/                              # authored or generated
```

`metadata.yaml` declares the immutable slug/version, entrypoint, seed, opening
prompt, repository contract, enabled tools, budgets, component paths, context
targets, and score weights. Component paths must remain beneath the scenario
root. Database, failure, and Browser components are optional; a scenario must
not create fake empty components merely to fit another scenario's shape.

The two design files are part of the scenario contract. They describe the
world, threat model, evidence surfaces, acceptable recovery paths, completion,
grading, security, and calibration in English and Simplified Chinese. Shared
Runner, isolation, account, API, and UI design stays in the root platform
design. Changing scenario truth requires a scenario version bump and both
scenario design editions in the same change.

Budgets distinguish active seconds, candidate tool calls, raw Provider HTTP
requests (including retries), and optional Provider-reported total Tokens.
Every enabled budget needs an ordered soft/hard pair. Do not invent a portable
dollar-cost budget from input/output Tokens; cache, reasoning, tier, discount,
and compatible-API semantics are not normalized.

`scenario.py` subclasses `Scenario` and implements `prepare()`,
`collect_artifacts()`, and `grade()`. It may return trusted
`verification_checks()` so the Worker can run scenario-specific checks without
knowing repository names or expected behavior. The default `run()` and
`archive()` may be overridden only when the scenario needs an auditable
protocol extension.

## Lifecycle contract

### `load()`

Validate metadata, SDK version, component containment, and the trusted Python
entrypoint. Loading must not create candidate state or contact a provider.

### `prepare()`

Create all state from the declared seed. Store candidate-visible content under
the returned workspace. Store fault scripts, canaries, golden state, and other
private references in `private_state`; do not copy hidden truth into the
workspace.

### `run()`

Use the injected executor so a scenario remains provider-agnostic. Tool,
hypothesis, evidence, fault, policy, and resource events must use normalized
event forms.

### `collect_artifacts()`

Collect only candidate outputs required by the scenario, such as repository
diff/status, a report, a generated plan, or a bounded diagnostic transcript.
Do not assume every scenario has a writable patch repository. Artifact
collection failures must be explicit and must not leak private truth.

### `verification_checks()`

Return named `ScenarioCheck` callbacks for host-side source contracts,
repository integrity, runtime replay, provenance, report requirements, or
other objective gates. Checks execute after artifact collection and before the
private grader. Keep expected values in `PreparedScenario.private_state`, not
in Worker code or the candidate workspace.

### `grade()`

Grade observable behavior and hidden verification. Never trust candidate
claims. Replay patches against fresh state. Return dimension scores, maximums,
evidence references, and any hard caps.

### `archive()`

Archive enough data to reproduce and audit the score while excluding provider
keys and hidden grader material. Hash artifacts.

## Determinism rules

- A fixed slug, version, seed, and scale must generate the same truth.
- Script every failure sequence; do not sample faults during a run.
- Use stable synthetic timestamps, identities, and commit messages.
- Store the selected fault transcript and generator metadata in the archive.
- Never rely on a live website, mutable package tag, or wall-clock date.
- Bump the scenario version when truth, expected patch, fault order, corpus, or
  scoring semantics change.

## Difficulty with a solve path

Contradictory evidence should have explainable provenance. For each scenario,
write a private truth table that labels sources as true, false, stale,
speculative, or malicious. Ensure at least two independent high-trust signals
support the intended conclusion.

Noise should tax prioritization, not require exhaustive reading. Prompt
injections should measure data/instruction separation, not depend on secret
phrasing. Tool faults must eventually permit a principled recovery.

## Truth Graph and acceptable solutions

Do not reduce private truth to one root-cause sentence or one exact patch.
Build a private `TruthGraph` with typed cause, condition, symptom, constraint,
invariant, and remediation nodes. Connect them with declared edges and define
one or more `ResolutionPath` objects:

- `required_nodes` are conjunctive;
- each `any_of_nodes` group requires one alternative;
- `required_checks` must come from objective hidden verification;
- `minimum_causal_coverage` prevents a lucky repair with no adequate model of
  the incident.

Use `evaluate_truth_graph()` in the trusted grader and expose only permitted
IDs and aggregate coverage. Never copy graph labels, accepted paths, or hidden
checks into the candidate workspace. Partial coverage may earn analysis credit
without becoming a pass.

If a published scenario previously accepted only one path, add alternatives in
a new scenario version. Never change private acceptance under an unchanged
slug/version.

## Project-mediated observability

New incident scenarios may opt into `process_list`, `service_status`,
`journal_query`, `socket_snapshot`, `trace_process`, and `profile_cpu`. These
are deterministic analogues of common operating-system tools, not host
passthrough. Their output must derive from the versioned Incident Director
state and include collector/clock provenance. Never expose a host PID, socket,
packet, service manager, or tracing capability.

Software-supply-chain scenarios may opt into the Release Director tools:
`release_status`, `registry_inspect`, `provenance_query`,
`attestation_verify`, `runtime_probe`, `release_snapshot`, `release_action`,
`release_verify`, and `submit_release_decision`. Artifact digests, signers,
trusted roots, recovery targets, and accepted paths remain private. The public
`release` metadata declares only observable coverage, containment/snapshot
requirements, decisions, and verification sequence.

Do not expose a real registry, orchestrator, Docker daemon, network, signing
key, or host trust store. The Director must be deterministic from scenario
seed and action sequence, audit denied actions, and make irreversible choices
explicit.

## Grading checklist

- Hidden functional regression on fresh state.
- Mutation cases that reject hard-coded visible answers.
- Static scope and generated/oracle-file checks.
- Golden replay from the stored fault transcript.
- Resource and repeated-read accounting.
- Security canaries for direct, authority, tool, and data injection.
- Hypothesis evolution and evidence-graph quality.
- A minimal golden patch and a documented alternative-correctness policy.
- A soft-budget reference solve.

## Validation

Build a cheap scaled package while iterating:

```bash
make challenge-smoke
```

Run backend validation:

```bash
cd apps/api
uv run pytest
uv run ruff check .
```

Before release, generate the full scenario twice into separate temporary
locations and compare normalized manifests and truth hashes. Do not commit the
generated workspaces.
