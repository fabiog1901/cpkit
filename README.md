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
- A standard CLI with `serve` and `migrate`

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
poetry run todo migrate
poetry run todo serve --reload
```

Then open:

- Web console: `http://localhost:8000/`
- API docs: `http://localhost:8000/api/docs`

For app webapp ports, use
[`resources/webapp_extension_guide.md`](resources/webapp_extension_guide.md)
as the reusable cpkit template extension guide.

## Project Status

cpkit is independent and evolving. The APIs are not yet stable, and the TODO app
is the current reference for the recommended application structure.

Expect the framework to keep moving toward a clearer extension model: cpkit owns
the operational platform, while applications plug in business logic.
