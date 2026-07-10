# cpkit

cpkit is an early-stage framework for building small control-plane applications
on FastAPI and Postgres-compatible databases.

It is meant for applications that need more than CRUD endpoints but should not
have to rebuild the same operational foundation every time: authentication,
settings, audit logging, job execution, playbook storage, database wiring, and a
basic web console.

cpkit is still immature, but it is already usable as a foundation for apps that
want to focus on their domain model while inheriting common control-plane
capabilities.

## Why cpkit?

Control-plane apps tend to repeat the same infrastructure:

- API key and OIDC authentication
- role-aware API dependencies
- durable settings stored in the database
- audit events and request logging
- durable job queues and background workers
- versioned playbooks and Ansible execution
- consistent service/repository error handling
- a minimal admin web UI

cpkit packages those pieces as framework capabilities. The application provides
its business routers, services, repositories, models, and job handlers; cpkit
provides the surrounding platform.

## What You Get

- FastAPI app bootstrap with cpkit routers mounted under `/api`
- A repository base class for framework-owned tables
- Built-in settings, events, jobs, API keys, auth, and playbooks APIs
- A durable message queue and worker loop for application jobs
- OIDC sessions and signed API-key authentication
- Request logging and audit event helpers
- A packaged template webapp for framework/admin pages
- A standard CLI with `serve` and `init`

## Install

Applications should depend on cpkit from PyPI:

```bash
pip install cpkit
```

In an application package, declare cpkit as a normal dependency:

```toml
[project]
dependencies = [
    "cpkit",
]
```

During local cpkit framework development, examples may use a path dependency
instead, such as `cpkit = {path = "../..", develop = true}`. Published apps
should use the PyPI dependency form.

cpkit also ships framework resources inside the Python package, including the
framework DDL at `cpkit/resources/ddl.sql`. Application code can locate it with:

```python
from cpkit import cpkit_ddl_path
```

The built-in cpkit CLI uses that packaged DDL automatically when running
`init`.

## Database Requirement

cpkit requires a PostgreSQL-compatible database. It is designed for Postgres-ish
SQL and has been developed around PostgreSQL/CockroachDB-style behavior.

Good options include:

- PostgreSQL
- CockroachDB
- Embedded/dev helpers such as the Python package `pgembed`

Set `CPKIT_DB_URL` to the database URL before running schema initialization or
serving an app.

## Try The TODO Example

The best way to understand cpkit is to run the TODO example:

[examples/todo_app](examples/todo_app)

The example is intentionally small, but it is not toy scaffolding. It shows a
real cpkit app with:

- its own `todos` table
- TODO API routes
- a service layer
- a repository extending cpkit's repository base
- a cpkit-managed FastAPI app
- cpkit settings, events, jobs, API keys, auth, and playbooks
- an `EXPORT_TODOS` job that writes TODOs to JSON or CSV files

Run it:

```bash
cd examples/todo_app
poetry install
export CPKIT_DB_URL='postgres://...'
export CPKIT_MASTER_KEY='base64-encoded-32-byte-key'
poetry run todo init
poetry run todo serve --reload
```

The TODO example uses a local path dependency on cpkit because it lives inside
this repository. A real app outside this repository should depend on cpkit from
PyPI.

Then open:

- Web console: `http://localhost:8000/`
- API docs: `http://localhost:8000/api/docs`

## Project Status

cpkit is independent and evolving. The APIs are not yet stable, and the TODO app
is the current reference for the recommended application structure.

Expect the framework to keep moving toward a clearer extension model: cpkit owns
the operational platform, while applications plug in business logic.
