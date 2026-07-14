# cpkit TODO App Example

This example is a small but useful cpkit application. It demonstrates how an
application extends cpkit with its own models, repository methods, service
logic, API router, DDL, and job handlers while relying on cpkit for auth,
settings, audit events, jobs, API keys, playbooks, database wiring, logging,
CLI behavior, and the template webapp.

## Run

This example uses a local editable path dependency on cpkit because it lives
inside the cpkit repository. An app outside this repository would normally use
`pip install cpkit` or declare `"cpkit"` as a package dependency.

cpkit needs a PostgreSQL-compatible database. PostgreSQL, CockroachDB, or a
development helper such as the Python package `pgembed` are suitable options.
Set `CPKIT_DB_URL` before running `init`.

```bash
cd examples/todo_app
poetry install
export CPKIT_DB_URL='postgres://...'
export CPKIT_MASTER_KEY='base64-encoded-32-byte-key'
poetry run todo init
poetry run todo serve --reload
```

The app mounts cpkit's template webapp at `/` and the API at `/api`.
It also contributes a small webapp extension at `/app` that adds a Todos page
to the cpkit shell with separate HTML, CSS, and JavaScript files.

The extension also demonstrates dashboard composition. Its
`cpkit-extension-dashboard` template contains multiple direct dashboard cards
with stable `data-dashboard-key` values; cpkit renders those cards as draggable
siblings next to the built-in Jobs and Events cards.

The app also demonstrates settings-backed cpkit playbook defaults.
`[tool.cpkit].playbooks` points at `resources/playbooks`; `todo init` loads the
app-provided `EXPORT_TODOS` playbook and the two reserved SSH credential hook
playbooks. The SSH hooks are no-op placeholders showing how an app can package
`SSH_CREDENTIAL_PREPARE` and `SSH_CREDENTIAL_CLEANUP` while CPKit manages hook
enablement through the Settings API/UI.

## API

- `GET /api/todos/`
- `POST /api/todos/`
- `PATCH /api/todos/{todo_id}`
- `DELETE /api/todos/{todo_id}`
- `POST /api/todos/export`

The export endpoint enqueues an `EXPORT_TODOS` job. The worker gathers rows and
then runs the `EXPORT_TODOS` playbook to write a JSON or CSV file under
`exports/`.
