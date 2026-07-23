.PHONY: bootstrap dev test lint build up down sandbox sandbox-smoke challenge preflight

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

down:
	docker compose down
