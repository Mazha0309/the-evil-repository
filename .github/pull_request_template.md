## What changed

<!-- Describe behavior and scope. -->

## Why

<!-- Link an issue or explain the benchmark/security need. -->

## Validation

- [ ] `make lint`
- [ ] `make test`
- [ ] `pnpm build`
- [ ] `make challenge-smoke` when scenario code changed

## Benchmark and security review

- [ ] Determinism is preserved or the scenario version was bumped.
- [ ] Hidden truth and provider credentials cannot enter candidate-visible data.
- [ ] Sandbox/tool/archive boundary changes received explicit review.
- [ ] `DESIGN.md` and threat/authoring docs were updated where relevant.
- [ ] No generated workspace, database, run archive, or secret is committed.
