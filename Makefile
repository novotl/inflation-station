.DEFAULT_GOAL := help

COMPARE_BRANCH ?= origin/main

.PHONY: help install lint test cov htmlcov check build

help: ## List the targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

install: ## Create .venv with dev dependencies and enable git hooks
	uv sync --locked
	uv run pre-commit install

lint: ## Run every pre-commit hook on all files
	uv run pre-commit run --all-files --show-diff-on-failure

test: ## Run the tests, with the total coverage floor
	uv run pytest

cov: ## Run the tests, write coverage.xml and fail on changed lines without coverage vs COMPARE_BRANCH (default origin/main)
	rm -f diff-cover.md
	uv run pytest --cov-report=xml
	uv run diff-cover coverage.xml --compare-branch=$(COMPARE_BRANCH) --branch-coverage --fail-under=100 \
		--format markdown:diff-cover.md

htmlcov: ## Run the tests and write a browsable coverage report to htmlcov/
	uv run pytest --cov-report=html

check: lint test cov ## Everything CI runs

build: ## Build the sdist and wheel into dist/
	uv build
