# LANSH make targets. Run `make help` for the list.
SHELL := /bin/bash
.DEFAULT_GOAL := help

# Java 21 everywhere (plan decision L4). Override with LANSH_JAVA_HOME on other machines.
JAVA21_CANDIDATES := /opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home \
                     /usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home \
                     /usr/lib/jvm/java-21-openjdk-amd64 /usr/lib/jvm/java-21-openjdk-arm64 \
                     /usr/lib/jvm/java-21-openjdk
LANSH_JAVA_HOME ?= $(firstword $(wildcard $(JAVA21_CANDIDATES)))
export JAVA_HOME := $(LANSH_JAVA_HOME)

UV ?= uv
RUN := $(UV) run
# the settings template; make setup copies it to .env
ENV_EXAMPLE := tests/fixtures/.env.example
COMPOSE := docker compose -f compose.yaml --env-file .env
PYTEST_MARKERS_ALL := "mssql or sas or live_llm or e2e or not (mssql or sas or live_llm or e2e)"

.PHONY: help setup check lint fmt test test-mssql test-sas test-live test-e2e test-all smoke \
        legacy-up legacy-down legacy-logs data load golden legacy-verify legacy-verify-all \
        third-party ui demo

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'
	@echo "  JAVA_HOME=$(JAVA_HOME)"

setup: ## Install Python 3.14 and every dependency with uv
	$(UV) sync
	@test -f .env || (cp $(ENV_EXAMPLE) .env && echo "Created .env from $(ENV_EXAMPLE): set MSSQL_SA_PASSWORD")

check: lint test ## Lint and run the offline tests (must pass before merging)

lint: ## ruff lint and format check
	$(RUN) ruff check .
	$(RUN) ruff format --check .

fmt: ## Apply ruff formatting and safe fixes
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

test: ## Offline unit tests (no Docker, SAS or Claude)
	$(RUN) pytest

test-mssql: ## Integration tests that need the SQL Server container
	$(RUN) pytest -m mssql

test-sas: ## Integration tests that need SAS OnDemand
	$(RUN) pytest -m sas

test-live: ## Tests that make live Claude Code calls (uses subscription quota)
	$(RUN) pytest -m live_llm

test-e2e: ## End-to-end factory runs in replay mode (offline, a few minutes)
	$(RUN) pytest -m e2e

test-all: ## Every test, including integration tests
	$(RUN) pytest -m $(PYTEST_MARKERS_ALL)

smoke: ## Environment smoke test: Spark+Delta, sqlglot, SQL Server, Claude Code, SAS
	$(RUN) python scripts/smoke_test.py

legacy-up: ## Start SQL Server 2022 (password from .env) and wait until it is healthy
	@test -f .env || (echo "Missing .env: copy $(ENV_EXAMPLE) to .env and set MSSQL_SA_PASSWORD" && exit 1)
	$(COMPOSE) up -d --wait

legacy-down: ## Stop SQL Server (the data volume is kept)
	$(COMPOSE) down

legacy-logs: ## Tail the SQL Server log
	$(COMPOSE) logs -f --tail=50

data: ## Generate the synthetic insurer (seeded, deterministic)
	$(RUN) lansh estate generate

load: ## Load the synthetic data into a fresh legacy database
	$(RUN) lansh estate load

golden: ## Run every legacy job on its real engine and capture golden outputs
	$(RUN) lansh estate golden --all

legacy-verify: ## Re-run the T-SQL jobs and check they reproduce the golden hashes
	$(RUN) lansh estate verify

legacy-verify-all: ## Same, plus the SAS jobs on SAS OnDemand
	$(RUN) lansh estate verify --sas

third-party: ## Refresh the package table in THIRD_PARTY.md from installed metadata
	$(RUN) python scripts/third_party.py

ui: ## Open the Control Tower (Streamlit) on the runs in runs/
	$(RUN) lansh ui

demo: ## Offline demo: replay T04 through all five stages, then open the Control Tower (no Docker, SAS or Claude)
	LANSH_LLM_MODE=replay $(RUN) lansh run-job T04 --run demo --mode replay
	$(RUN) lansh ui
