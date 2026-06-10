# Convenience commands for local development and repository maintenance.
#
# Usage:
#   make help           Show available targets.
#   make format         Format Python code with isort and black.
#   make codemap-write  Refresh deterministic CODEMAP.md and .build index.
#   make pre-commit     Run required checks before committing.

.PHONY: help format codemap-write codemap-check pre-commit py-compile

help: ## Show this help message.
	@awk 'BEGIN {FS = ":.*##"; printf "Available targets:\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

format: ## Format Python code with isort and black.
	poetry run isort .
	poetry run black .

codemap-write: ## Refresh deterministic CODEMAP.md and .build/project-index.json.
	poetry run python tools/codemap.py --write

codemap-check: ## Verify deterministic codemap outputs are current.
	poetry run python tools/codemap.py --check

pre-commit: format codemap-write py-compile ## Run required pre-commit maintenance.

py-compile: ## Compile Python files to catch syntax errors.
	poetry run python -m compileall cpkit tools examples/todo_app/todo_app
