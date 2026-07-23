# Changelog

All notable platform changes are recorded here. The project follows Semantic
Versioning while individual benchmark scenarios retain independent versions.

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
