# Scenario Authoring

A scenario is a versioned directory package. React never interprets its
contents; the trusted Runner loads it through the Scenario SDK.

## Required layout

```text
scenarios/example/
├── metadata.yaml
├── scenario.py
├── repos/repositories.yaml
├── database/{init,dirty,hidden}.sql
├── injections/
├── failures/{filesystem,command,browser}.yaml
├── grading/{public.yaml,hidden.py,replay.py}
└── mirror/
```

`metadata.yaml` declares the immutable slug/version, entrypoint, seed, opening
prompt, repository contract, enabled tools, budgets, component paths, context
targets, and score weights. Component paths must remain beneath the scenario
root.

`scenario.py` subclasses `Scenario` and implements `prepare()` and `grade()`.
The default `run()` and `archive()` may be overridden only when the scenario
needs an auditable protocol extension.

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
