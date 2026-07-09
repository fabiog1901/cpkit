# cpkit Code Map

cpkit is an application framework for FastAPI apps that want the same
operational backbone: authentication, audit events, settings, jobs, playbooks,
database helpers, and a shared webapp shell.

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
