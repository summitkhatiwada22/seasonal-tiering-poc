.DEFAULT_GOAL := help
.PHONY: help setup test lint format typecheck check synth status data simulate reproduce report

help: ## Show this list
	@grep -E '^[a-z_]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

setup: ## Install pinned dependencies and create data folders
	uv sync
	mkdir -p data/raw data/interim data/processed

test: ## Run the test suite
	uv run pytest

lint: ## Check code style (no changes made)
	uv run ruff check .
	uv run ruff format --check .

format: ## Fix code style automatically
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## Run the static type checker
	uv run mypy

check: lint typecheck test ## Run everything CI runs

synth: ## Generate small synthetic data (D7) into data/processed/synthetic_S
	uv run python -m sat.synth --scale S --out data/processed/synthetic_S

status: ## Show which phase we are on and where we can stop
	@sed -n '/<!-- STATUS-START -->/,/<!-- STATUS-END -->/p' docs/PROGRESS.md | grep -v '<!--'

data: ## (Phase 2) Download and convert real datasets
	@echo "Not built yet: arrives in Phase 2."; exit 1

simulate: ## (Phases 3-6) Run cost simulator and policies
	@echo "Not built yet: arrives in Phases 3-6."; exit 1

reproduce: ## (Phase 7) Rebuild every headline number from scratch
	@echo "Not built yet: arrives in Phase 7."; exit 1

report: ## (Phase 10) Build the results page
	@echo "Not built yet: arrives in Phase 10."; exit 1
