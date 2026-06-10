# Repository Maintenance Guide

This guide defines the shared maintenance workflow for cpkit-based projects.
It is intended to be durable instruction for humans and Codex when context is
lost.

## Goals

- Formatting is always applied before a commit.
- The deterministic code map is refreshed before a commit.
- Full docs generation remains an explicit, on-demand action.
- The same project-agnostic tooling is used by cpkit applications.

## Shared Code Map Tool

Use the project-local deterministic code map generator:

```bash
poetry run python tools/codemap.py --write
```

The default outputs are:

- `CODEMAP.md`
- `.build/project-index.json`

The tool discovers package roots from `pyproject.toml` and importable package
directories. Extra application source roots can be included with repeated
`--source-root` options:

```bash
poetry run python tools/codemap.py --write --source-root workers
```

Do not include maintenance-only directories such as `tools/` in the code map.

Use check mode in CI or local verification:

```bash
poetry run python tools/codemap.py --check
```

## Recommended Makefile Targets

Each cpkit-based project should expose the same targets:

```makefile
.PHONY: format codemap-write codemap-check pre-commit docs-write docs-check py-compile

format: ## Format Python code with isort and black.
	poetry run isort .
	poetry run black .

codemap-write: ## Refresh deterministic CODEMAP.md and .build/project-index.json.
	poetry run python tools/codemap.py --write

codemap-check: ## Verify deterministic code map outputs are current.
	poetry run python tools/codemap.py --check

pre-commit: format codemap-write py-compile ## Run required pre-commit maintenance.
```

Projects may add app-specific checks to `pre-commit`, but docs builds should
stay out of `pre-commit` until the project explicitly decides otherwise.

## Documentation Policy

Documentation generation is on demand:

```bash
make docs-write
make docs-check
```

Generated docs may use the same `.build/project-index.json`, but refreshing
full docs should not be required before every commit.

Project-specific documentation generators may remain when they produce curated
or site-specific docs. They should not own the canonical code map workflow.
Code map generation should come from `tools/codemap.py`.

## Codex Instruction

When preparing a commit in a cpkit-based project:

```text
Read resources/repository_maintenance_guide.md. Before committing, run
make format and refresh the deterministic code map with make codemap-write or
make pre-commit. Do not regenerate full docs unless explicitly requested.
```
