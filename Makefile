.PHONY: bootstrap dev test lint build up deploy deploy-public production-check down sandbox sandbox-smoke challenge preflight version-check

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
	cd apps/api && uv run ruff check .
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

challenge:
	cd apps/api && uv run python -m app.scenario.cli --scenario ../../scenarios/terminal-repository --output ../../generated/terminal-repository

challenge-smoke:
	cd apps/api && uv run python -m app.scenario.cli --scenario ../../scenarios/terminal-repository --output ../../generated/terminal-repository-smoke --scale 0.02

preflight:
	./scripts/rootless-preflight.sh

up: sandbox
	docker compose up --build -d

deploy: preflight sandbox
	docker compose up --build -d
	docker compose ps

production-check:
	test -f .env.production
	! grep -q "CHANGE_ME" .env.production
	grep -Eq '^WEB_ORIGIN=https://' .env.production
	grep -Eq '^SESSION_COOKIE_SECURE=true$$' .env.production

deploy-public: preflight sandbox production-check
	docker compose --env-file .env.production up --build -d
	docker compose --env-file .env.production ps

down:
	docker compose down
