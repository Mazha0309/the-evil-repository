# Contributing to The Evil Repository

Thank you for helping build a reproducible, security-conscious benchmark for
software agents.

## Before opening a change

- Read [`DESIGN.md`](DESIGN.md) for the benchmark contract.
- Read [`docs/threat-model.md`](docs/threat-model.md) before changing the
  Runner, sandbox, archive path, provider client, or tool protocol.
- Open a scenario proposal before adding a large corpus or a new canonical
  challenge.
- Never commit model-provider keys, real incident data, copyrighted mirrors,
  or private chain-of-thought transcripts.

## Local setup

Requirements are Linux, Rootless Docker, Node.js 22+, pnpm, Python 3.12+, and
uv.

```bash
cp .env.example .env
make preflight
make bootstrap
make sandbox
make sandbox-smoke
make test
make lint
```

Run a cheap deterministic scenario build while authoring:

```bash
make challenge-smoke
```

The full canonical corpus intentionally consumes substantially more time and
disk. Generate it with `make challenge`.

## Change expectations

A pull request should:

- be narrowly scoped and explain the behavior change;
- add or update tests for executable behavior;
- update `DESIGN.md` for architecture, protocol, scoring, or threat-model
  changes;
- preserve deterministic output for a fixed scenario version and seed;
- keep hidden grader state out of candidate workspaces and public events;
- include migration notes for persistent schema changes;
- pass `make lint`, `make test`, and `pnpm build`.

Scenario changes additionally need a documented truth model, an intended solve
path, replay coverage, prompt-injection canaries, a minimal golden patch, and a
soft-budget solvability check. See
[`docs/scenario-authoring.md`](docs/scenario-authoring.md).

## Commit and review hygiene

Use descriptive commits. Generated challenge workspaces, run archives,
databases, build products, and credentials must remain untracked. Reviewers
should treat modifications to isolation, archive extraction, command routing,
and hidden grading as security-sensitive.

By contributing, you agree that your contribution is licensed under
`AGPL-3.0-only`.
