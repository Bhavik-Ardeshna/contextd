SHELL := /bin/bash
COMPOSE := docker compose -f docker/docker-compose.yml

.PHONY: help start run start-build reset local-dev infra backend frontend worker migrate db-sync stop restart ps logs lint test build validate docker-build docker-build-backend docker-build-frontend docker-build-frontend-dev

help: ## Show available targets.
	@awk 'BEGIN {FS = ":.*##"; printf "ContextD commands:\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

start: ## Start the Docker dev stack with backend, worker, infra, and frontend hot reload.
	@NONINTERACTIVE=1 bash scripts/start-stack.sh

run: start ## Alias for start.

start-build: ## Rebuild images and start the Docker dev stack.
	@BUILD_IMAGES=1 NONINTERACTIVE=1 bash scripts/start-stack.sh

reset: ## Remove ContextD containers/data volumes, then start fresh.
	@RESET_CONTAINERS=1 NONINTERACTIVE=1 bash scripts/start-stack.sh

local-dev: ## Start infra in Docker, then backend/frontend/worker locally with hot reload.
	@NONINTERACTIVE=1 bash scripts/start-stack.sh --local-dev

infra: ## Start only infrastructure services needed by local app processes.
	@$(COMPOSE) up -d postgres redis milvus-etcd milvus temporal temporal-ui neo4j

backend: ## Run the backend locally with migrations and hot reload.
	@bash scripts/run-backend-local.sh

frontend: ## Run the frontend locally with Vite hot reload.
	@bash scripts/run-frontend-local.sh

worker: ## Run the Temporal worker locally.
	@bash scripts/run-worker-local.sh

migrate: ## Run backend database migrations.
	@cd backend && poetry run alembic upgrade head

db-sync: ## Seed/update configured source metadata from environment variables.
	@cd backend && poetry run python -m contextd.initial_data

stop: ## Stop the Docker stack.
	@$(COMPOSE) --profile frontend --profile frontend-dev down

restart: ## Restart the Docker dev stack.
	@$(MAKE) stop
	@$(MAKE) start

ps: ## Show ContextD Docker services.
	@$(COMPOSE) --profile frontend --profile frontend-dev ps

logs: ## Follow backend logs.
	@docker logs -f contextd-backend

lint: ## Run backend and frontend lint checks.
	@cd backend && POETRY_VIRTUALENVS_CREATE=true poetry run ruff check .
	@cd frontend && npm run lint

test: ## Run backend tests.
	@cd backend && POETRY_VIRTUALENVS_CREATE=true poetry run pytest -q --no-cov

build: ## Build the frontend production bundle.
	@cd frontend && npm run build

validate: lint test build ## Run lint, tests, and frontend build.

docker-build: ## Build backend, worker, frontend, and frontend-dev images.
	@$(COMPOSE) --profile frontend --profile frontend-dev build

docker-build-backend: ## Build backend image used by backend and worker.
	@$(COMPOSE) build backend temporal-worker

docker-build-frontend: ## Build production frontend image.
	@$(COMPOSE) --profile frontend build frontend

docker-build-frontend-dev: ## Build frontend hot-reload image.
	@$(COMPOSE) --profile frontend-dev build frontend-dev
