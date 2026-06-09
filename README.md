# cpkit

FastAPI control-plane framework code extracted from `cp`.

This package owns the framework mechanics: authentication, settings, audit
recording, database helpers, error handling, and other infrastructure that every
cpkit application should get consistently. Product-specific domains, request
models, event catalogs, and lifecycle behavior stay in the applications that
consume it.

## App Bootstrap

Applications create their FastAPI app through `create_cpkit_app`. The framework
owns the root app, `/api` subapp, database lifecycle, request logging middleware,
static webapp mount, startup hooks, and background task cancellation.

The application supplies its repository class, cpkit callback bundle, and domain
routers:

```python
from cp.repos import Repo
from cpkit import create_cpkit_app, create_cpkit_bundle

cpkit_capabilities = create_cpkit_bundle(
    command_models=COMMAND_MODELS,
    command_handlers=COMMAND_HANDLERS,
    reschedule_type_map={CREATE_COMMAND: RECREATE_COMMAND},
)

app = create_cpkit_app(
    title="my-control-plane",
    version="0.1.0",
    repo_class=Repo,
    db_url=CPKIT_DB_URL,
    capabilities=(cpkit_capabilities,),
    routers=(domain_router,),
    static_directory="webapp",
)
```

cpkit initializes the database pool from `db_url`, configures the repository
factory, mounts its built-in routers, starts its background tasks, runs its
startup validation, and exposes the configured repository through
`cpkit.get_repo()`.

cpkit owns event emission through `cpkit.audit.log_event`, including best-effort
writes and request id propagation. Applications with a custom audit row model
can pass `audit_record_factory` to teach cpkit how to build that model.

## OIDC Integration

OIDC is configured through framework settings stored in the `cpkit.settings`
table. `create_cpkit_bundle` wires the OIDC/API-key auth router and exposes
auth dependencies through stable cpkit exports such as `require_user`,
`require_readonly`, `require_admin`, `get_access_scope`, and `get_audit_actor`.

After wiring this router into the app, cpkit handles the `/auth/login`,
`/auth/callback`, `/auth/logout`, and `/auth/me` flow, plus API-key header
authentication through `X-CP-Access-Key`, `X-CP-Signature`, and `X-Timestamp`.

OIDC session persistence is stored in `cpkit.oidc_sessions`; OIDC configuration
is stored as settings rows in `cpkit.settings`.

The admin settings API is provided by `create_settings_router`; applications
supply their service dependency, audit actor dependency, and service error
handler.

## Logging Integration

Logging is provided by `cpkit.logging`. Framework settings in `cpkit.settings`
control the runtime log level and journald identifier:

- `logging.level`
- `logging.journald_identifier`

`create_cpkit_app` configures logging and installs request logging middleware.
Applications that need lower-level control can still use the logging helpers
directly:

```python
from cpkit.logging import configure_logging, request_logging_middleware

configure_logging(get_repo(), force=True, default_journald_identifier="cp")


@app.middleware("http")
async def dispatch(request, call_next):
    return await request_logging_middleware(request, call_next)
```

`request_logging_middleware` manages the request id context, emits inbound and
outbound request logs, and adds `X-Request-ID` plus `X-Process-Time-ms` response
headers.

## Jobs Integration

The framework owns the durable message queue and worker polling loop. The queue
table lives in `cpkit.mq`; applications extend `CPKitRepo` and supply command
payload models plus handlers through `create_cpkit_bundle`.

Applications still own business job semantics:

- command enums and payload models
- handler functions
- application job/task metadata
- failure bookkeeping

```python
from cpkit import CPKitRepo


class Repo(AppDomainRepo, CPKitRepo):
    ...
```

This keeps queue claiming, dispatch, deletion, polling jitter, and cancellation
handling in cpkit while leaving job behavior to the consuming app.

## Playbooks and Ansible

The framework owns versioned playbook storage and the generic Ansible execution
engine. The playbook table lives in `cpkit.playbooks`; applications extend
`CPKitRepo` for default/versioned playbook lookup and writes.
The admin playbooks API is provided by `create_playbooks_router`; applications
supply their service dependency, audit actor dependency, and service error
handler.

Applications still own the domain contract around playbooks:

- allowed playbook names
- admin API/service responses and audit events
- extra vars construction
- business state transitions after a playbook succeeds or fails

Remote workers can ask cpkit to run a stored playbook with application-specific
repository and status values:

```python
from cpkit import CPKitRepo
from cpkit.playbooks import run_playbook


class Repo(AppDomainRepo, CPKitRepo):
    ...


result = run_playbook(
    repo=repo,
    job_id=job_id,
    playbook_name=playbook_name,
    extra_vars=extra_vars,
    running_status="RUNNING",
    completed_status="COMPLETED",
    failed_status="FAILED",
)
```
