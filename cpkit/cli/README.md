# CLI

The CLI package gives cpkit-backed applications a small reusable command line
interface. It is meant for app projects, not as a standalone cpkit server.

## Files

- `base.py`: `ApplicationCLI`, the main CLI implementation.
- `schema.py`: SQL schema initialization and preflight helpers.
- `server.py`: Uvicorn serving helper.
- `__main__.py`: Allows running the package as a module when exposed by an app.

## Runtime Flow

`ApplicationCLI.from_project()` reads `pyproject.toml` and environment variables
to discover the app import path, DDL files, playbook directories, schema checks,
and DB URL variable. The app can then expose commands like:

- `init`: initialize cpkit and app schemas from DDL files.
- `disable-oidc`: set `oidc.enabled` to `false` for lockout recovery.
- `serve`: run the configured FastAPI app with Uvicorn.

## OIDC Lockout Recovery

If OIDC settings lock users out of the web UI, use the application CLI to
disable OIDC directly in `cpkit.settings`:

```bash
CPKIT_DB_URL=postgres://... my-app disable-oidc
```

Use the app-specific DB URL environment variable if the app configured one with
`db_url_env`, for example `KLOIGOS_DB_URL`. Restart the application after the
command so startup and auth state reload from the updated setting.

## Playbook Initialization

`init` can also load application-provided default playbooks into
`cpkit.playbooks`. Apps tell cpkit where playbook files live; cpkit owns the
database mechanics.

Configure directories in `pyproject.toml`:

```toml
[tool.cpkit]
playbooks = [
    "kloigos/resources/playbooks",
]
```

Or override them with `CPKIT_APP_PLAYBOOKS`, using comma-separated paths.

Accepted playbook file extensions are `.yaml`, `.yml`, and `.json`. Hidden
files and unsupported extensions are ignored. The file stem becomes the
playbook name exactly as written.

Initialization is idempotent: if the file content matches the current default
content, no new version is created. If content differs, cpkit creates a new
version and makes it the default.

Apps packaged for pip can resolve package resources themselves and pass normal
paths into `ApplicationCLI`:

```python
from pathlib import Path

from cpkit import ApplicationCLI

PACKAGE_ROOT = Path(__file__).resolve().parent

def package_path(relative_path: str):
    return PACKAGE_ROOT / relative_path


cli = ApplicationCLI(
    app_name="kloigos",
    app_import="kloigos.main:app",
    db_url_env="KLOIGOS_DB_URL",
    app_ddl_paths=(package_path("resources/database/ddl.sql"),),
    app_playbook_dirs=(package_path("resources/playbooks"),),
)
```

cpkit should not know app package names. Apps resolve their own resources and
pass regular paths into cpkit.
