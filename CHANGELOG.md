# Changelog

All notable platform changes are recorded here. The project follows Semantic
Versioning while individual benchmark scenarios retain independent versions.

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
