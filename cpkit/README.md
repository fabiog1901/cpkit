# cpkit Code Map

cpkit is an application framework for FastAPI apps that want the same
operational backbone: authentication, audit events, settings, jobs, playbooks,
database helpers, and a shared webapp shell.

Installed apps should consume cpkit as a normal Python dependency, for example
`pip install cpkit` or a `[project.dependencies]` entry of `"cpkit"`.

The package is organized by capability. The directories look flat at first
glance, but most capability packages use the same internal pattern:

- `types.py`: Pydantic models, enums, and response shapes.
- `repository.py` or `repositories.py`: database mixins for framework-owned
  tables.
- `service.py`: business rules and repository error translation.
- `router.py`: FastAPI routes and dependency wiring.
- `__init__.py`: public exports for that capability.

The main app flow is:

1. An app calls `create_cpkit_bundle()` from `bundle.py` to assemble cpkit
   capabilities.
2. The app calls `create_cpkit_app()` from `app.py` to create the FastAPI app,
   configure the repository, run startup hooks, mount routers, and launch
   background tasks.
3. `repository.py` provides `CPKitRepo`, a mix of all framework repository
   capabilities. Apps can subclass it and add their own repository methods.
4. Capability services use `get_repo()` to work with the configured app repo.
5. The shared webapp in `webapp/` talks to the framework API routes and can be
   extended by app-owned web assets.

## Application Shutdown

`create_cpkit_app()` owns application background tasks and the standard bundle's
registered queue worker. Shutdown stops polling, cancels/observes background
tasks, drains actual handler invocations and failure hooks, joins the workers'
executors, then closes the shared database pool. Startup failure and lifespan
exceptions use the same cleanup path. Completed background-task failures are
surfaced after cleanup; simultaneous application/background failures are grouped.
A handler failure continues to use its registered failure hook and job status.

The default `shutdown_timeout=None` waits for completion. Configure a finite
asynchronous wait budget when the host needs an observable incomplete shutdown:

```python
app = create_cpkit_app(
    title="Control Plane", version="1", db_url=db_url,
    get_repo=get_repo, bundles=(bundle,), shutdown_timeout=10,
)
```

An expired budget raises `AppShutdownIncomplete`, whose `runtime` and `result`
retain the original owner and snapshot. Shutdown cancellation propagates
`CancelledError`. In either case the owner remains at
`app.state.cpkit_runtime`; incomplete work keeps the pool open. After the handler
can finish, use the same event loop to observe and retry cleanup:

```python
runtime = app.state.cpkit_runtime
status = runtime.status
# status.unresolved contains original HandlerCompletion objects.
# status.pending_tasks and status.task_errors describe app background tasks.
result = await runtime.shutdown(timeout=10)
if result.complete:
    assert result.pool_closed
```

`runtime.pool` retains the original pool reference. Repeated shutdown calls
continue draining, rather than re-dispatching work or repeatedly cancelling task
cleanup. The pool is closed once, after a completed drain. If the globally
configured pool has been replaced, the retained owner refuses to close the
replacement. An unfinished runtime cannot be overwritten by re-entering the same
app's lifespan.

A cancelled lifespan body requests stop and checks cleanup without waiting before
propagating cancellation. A cancellation during cleanup interrupts waiting. Both
leave unfinished cleanup available through the runtime. Keep the event loop and
shared resources alive until a later shutdown completes. CPKit cannot terminate
arbitrary handler threads or external operations. Synchronous database/cleanup
calls can delay event-loop timeouts, so the budget is not a hard process-exit
or handler-termination deadline.

Workers are discovered through `bundle.queue_worker` and `QueueWorker` instances
registered directly as background factories. Background factory iterables are
materialized when the app is created, so direct workers are retained before
startup hooks can dispatch or fail. The factories themselves are invoked after
startup hooks. Register workers explicitly rather than hiding their ownership
inside closures. Custom background tasks retain their
normal coroutine cancellation contract; CPKit does not infer external work they
may have started. The shared database/repository configuration remains application
wide, and worker instances remain single-use.

## Architecture Review

The current flat capability layout is reasonable for cpkit's size. It keeps
imports readable and makes each framework feature easy to find. A deeper layout
like `cpkit/core`, `cpkit/capabilities`, and `cpkit/integrations` might become
useful later, but moving there now would mostly create import churn.

The part that made the project feel like a black box was not the package shape;
it was the lack of an orientation layer. These README files are intended to be
that layer. They explain the module boundaries without changing runtime code.

Good rules of thumb:

- Start in `bundle.py` when asking "how does cpkit assemble itself?"
- Start in `app.py` when asking "how does cpkit become a FastAPI app?"
- Start in `repository.py` when asking "how do framework services reach the DB?"
- Start in a capability package when asking about one feature area.
- Start in `webapp/README.md` for frontend extension behavior.

## Top-Level Modules

- `app.py`: FastAPI app bootstrap, lifespan management, router mounting, static
  webapp mounting, DB initialization, and background task startup.
- `bundle.py`: The standard cpkit capability bundle. It wires auth, jobs,
  events, admin routes, settings, playbooks, API keys, audit hooks, and the
  queue worker.
- `repository.py`: The framework repository composition point. `CPKitRepo`
  combines all cpkit repository mixins; `configure_repository()` tells cpkit how
  to create app repo instances.
- `resources/`: Packaged framework resources such as `ddl.sql`. Use
  `cpkit_ddl_path()` to locate them from installed wheels.
- `admin.py`: Composes built-in admin routers under the admin API prefix.
- `dependencies.py`: Global dependency accessors used by routers after a bundle
  has been configured.
- `time.py`: Shared timestamp formatting constants.

## Capability Packages

- `audit/`: audit event records, event reads, audit hooks, and the context used
  to attach request/job identifiers.
- `auth/`: OIDC login/logout, API key auth, role/group mapping, encrypted
  secrets, and auth dependencies.
- `cli/`: reusable app CLI for schema initialization, schema checks, and serving.
- `config/`: small environment/config helpers.
- `db/`: database pool, query helpers, Cockroach/Postgres compatibility, and
  DB error translation.
- `errors/`: repository/service/http exception layers.
- `jobs/`: framework job table, queue table, queue worker, job APIs, and job
  rescheduling.
- `logging/`: request id context, middleware, and logging setup.
- `playbooks/`: versioned playbook storage and Ansible runner integration.
- `settings/`: framework settings table and admin settings API.
- `webapp/`: static HTML/CSS/JS shell and extension contract for app UIs.
