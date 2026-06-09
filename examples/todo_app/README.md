# cpkit TODO App Example

This example is a small but useful cpkit application. It demonstrates how an
application extends cpkit with its own models, repository methods, service
logic, API router, DDL, and job handlers while relying on cpkit for auth,
settings, audit events, jobs, API keys, playbooks, database wiring, logging,
CLI behavior, and the template webapp.

## Run

```bash
cd examples/todo_app
poetry install
export CPKIT_DB_URL='postgres://...'
export CPKIT_MASTER_KEY='base64-encoded-32-byte-key'
poetry run todo migrate
poetry run todo serve --reload
```

The app mounts cpkit's template webapp at `/` and the API at `/api`.

## API

- `GET /api/todos/`
- `POST /api/todos/`
- `PATCH /api/todos/{todo_id}`
- `DELETE /api/todos/{todo_id}`
- `POST /api/todos/export`

The export endpoint enqueues an `EXPORT_TODOS` job. The worker writes a JSON or
CSV file under `exports/` and records the output path as a job task.
