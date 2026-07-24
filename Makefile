.PHONY: bootstrap dev test lint build up deploy deploy-public deploy-safety-check production-check down sandbox sandbox-smoke scenario-validate challenge challenge-smoke challenge-terminal challenge-counterfeit preflight version-check

SCENARIO ?= terminal-repository

bootstrap:
	pnpm install
	cd apps/api && uv sync --dev

dev:
	pnpm dev

test:
	pnpm test
	cd apps/api && uv run pytest

lint:
	pnpm lint
	cd apps/api && uv run ruff check . ../../scenarios
	./scripts/check-version.sh

version-check:
	./scripts/check-version.sh

build:
	pnpm build
	cd apps/api && uv build

sandbox:
	docker build -t evil-repository-sandbox:local infra/sandbox

sandbox-smoke: sandbox
	cd apps/api && DOCKER_HOST=unix:///run/user/$$(id -u)/docker.sock uv run python scripts/sandbox_smoke.py
	cd apps/api && DOCKER_HOST=unix:///run/user/$$(id -u)/docker.sock uv run python scripts/release_sandbox_smoke.py

scenario-validate: sandbox-smoke
	cd apps/api && uv run pytest tests/test_challenge_generation.py tests/test_incident_director.py tests/test_release_director.py tests/test_counterfeit_release_scenario.py tests/test_scenario_sdk.py

challenge:
	cd apps/api && uv run python -m app.scenario.cli --scenario ../../scenarios/$(SCENARIO) --output ../../generated/$(SCENARIO)

challenge-smoke:
	cd apps/api && uv run python -m app.scenario.cli --scenario ../../scenarios/$(SCENARIO) --output ../../generated/$(SCENARIO)-smoke --scale 0.02

challenge-terminal:
	$(MAKE) challenge SCENARIO=terminal-repository

challenge-counterfeit:
	$(MAKE) challenge SCENARIO=counterfeit-release

preflight:
	./scripts/rootless-preflight.sh

deploy-safety-check:
	./scripts/deploy-safety-check.sh

up: deploy-safety-check sandbox
	docker compose up --build -d

deploy: preflight deploy-safety-check sandbox
	docker compose up --build -d
	docker compose ps

production-check:
	test -f .env.production
	! grep -q "CHANGE_ME" .env.production
	grep -Eq '^WEB_ORIGIN=https://' .env.production
	grep -Eq '^SESSION_COOKIE_SECURE=true$$' .env.production

deploy-public: preflight deploy-safety-check sandbox production-check
	docker compose --env-file .env.production up --build -d
	docker compose --env-file .env.production ps

down: deploy-safety-check
	docker compose down
