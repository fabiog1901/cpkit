# CLI

The CLI package gives cpkit-backed applications a small reusable command line
interface. It is meant for app projects, not as a standalone cpkit server.

## Files

- `base.py`: `ApplicationCLI`, the main CLI implementation.
- `migration.py`: SQL migration and schema preflight helpers.
- `server.py`: Uvicorn serving helper.
- `__main__.py`: Allows running the package as a module when exposed by an app.

## Runtime Flow

`ApplicationCLI.from_project()` reads `pyproject.toml` and environment variables
to discover the app import path, DDL files, schema checks, and DB URL variable.
The app can then expose commands like:

- `migrate`: apply cpkit and app SQL.
- `check`: verify DB connectivity and required tables.
- `serve`: run the configured FastAPI app with Uvicorn.

