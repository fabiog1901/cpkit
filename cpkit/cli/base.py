"""Base application CLI for cpkit apps."""

import argparse
import os
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from .migration import apply_sql_file, check_database, check_table
from .server import serve_uvicorn


class ApplicationCLI:
    """Standard command-line interface for a cpkit-backed application."""

    def __init__(
        self,
        *,
        app_name: str,
        app_import: str,
        app_ddl_paths: Sequence[str | Path] = (),
        app_schema_checks: Sequence[str] = (),
        db_url_env: str = "DB_URL",
        cpkit_ddl_path: str | Path | None = None,
    ) -> None:
        self.app_name = app_name
        self.app_import = app_import
        self.app_ddl_paths = tuple(Path(path) for path in app_ddl_paths)
        self.app_schema_checks = tuple(app_schema_checks)
        self.db_url_env = db_url_env
        self.cpkit_ddl_path = Path(cpkit_ddl_path) if cpkit_ddl_path else None

    @classmethod
    def from_project(
        cls,
        *,
        project_root: str | Path | None = None,
        app_name: str | None = None,
    ) -> "ApplicationCLI":
        """Create an app CLI from pyproject.toml metadata."""
        root = Path(project_root or os.getcwd()).resolve()
        pyproject = _load_pyproject(root)
        project = pyproject.get("project", {})
        cpkit_config = pyproject.get("tool", {}).get("cpkit", {})
        effective_app_name = (
            app_name
            or os.getenv("CPKIT_APP_NAME")
            or cpkit_config.get("app_name")
            or project.get("name")
            or Path(sys.argv[0]).name
        )
        app_import = (
            os.getenv("CPKIT_APP_IMPORT")
            or cpkit_config.get("app_import")
            or f"{effective_app_name}.main:app"
        )
        ddl_paths = _configured_paths(
            root,
            os.getenv("CPKIT_APP_DDL"),
            cpkit_config.get("ddl"),
        )
        schema_checks = _configured_values(
            os.getenv("CPKIT_SCHEMA_CHECKS"),
            cpkit_config.get("schema_checks"),
        )
        cpkit_ddl = cpkit_config.get("cpkit_ddl")
        return cls(
            app_name=effective_app_name,
            app_import=app_import,
            app_ddl_paths=ddl_paths,
            app_schema_checks=schema_checks,
            cpkit_ddl_path=(root / cpkit_ddl) if cpkit_ddl else None,
        )

    def main(self, argv: Sequence[str] | None = None) -> int:
        """Run the application CLI."""
        args = self._parser().parse_args(argv)
        return int(args.handler(args) or 0)

    def migrate(self, _args: argparse.Namespace) -> int:
        """Apply cpkit schema and application schema SQL."""
        db_url = self._db_url()
        cpkit_ddl = self._cpkit_ddl_path()
        if cpkit_ddl is not None:
            print(f"Applying cpkit migration: {cpkit_ddl}")
            apply_sql_file(db_url, cpkit_ddl)

        for path in self.app_ddl_paths:
            print(f"Applying {self.app_name} migration: {path}")
            apply_sql_file(db_url, path)

        self._check_schemas(db_url)
        print("Migration complete.")
        return 0

    def serve(self, args: argparse.Namespace) -> int:
        """Run preflight checks and serve the FastAPI app."""
        db_url = self._db_url()
        self._check_schemas(db_url)
        serve_uvicorn(
            self.app_import,
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=args.log_level,
        )
        return 0

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=self.app_name)
        subparsers = parser.add_subparsers(dest="command", required=True)

        migrate = subparsers.add_parser("migrate", help="Apply database migrations.")
        migrate.set_defaults(handler=self.migrate)

        server = subparsers.add_parser("serve", help="Run the FastAPI application.")
        server.add_argument("--host", default="0.0.0.0")
        server.add_argument("--port", type=int, default=8000)
        server.add_argument("--reload", action="store_true")
        server.add_argument("--log-level", default="info")
        server.set_defaults(handler=self.serve)

        return parser

    def _db_url(self) -> str:
        db_url = os.getenv(self.db_url_env, "").strip()
        if not db_url:
            raise RuntimeError(f"{self.db_url_env} is not set.")
        return db_url

    def _check_schemas(self, db_url: str) -> None:
        print("Checking database connectivity.")
        check_database(db_url)
        print("Checking cpkit schema.")
        check_table(db_url, "cpkit.settings")
        for table_name in self.app_schema_checks:
            print(f"Checking application table: {table_name}")
            check_table(db_url, table_name)

    def _cpkit_ddl_path(self) -> Path | None:
        if self.cpkit_ddl_path is not None:
            return self.cpkit_ddl_path

        package_root = Path(__file__).resolve().parents[2]
        candidate = package_root / "resources" / "ddl.sql"
        if candidate.exists():
            return candidate
        return None


def main(argv: Sequence[str] | None = None) -> int:
    """Run the current project's cpkit application CLI."""
    return ApplicationCLI.from_project().main(argv)


def _load_pyproject(root: Path) -> dict:
    path = root / "pyproject.toml"
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text())


def _configured_paths(
    root: Path,
    env_value: str | None,
    config_value,
) -> tuple[Path, ...]:
    values = _configured_values(env_value, config_value)
    if values:
        return tuple(root / value for value in values)
    return tuple(path for path in _default_ddl_paths(root) if path.exists())


def _configured_values(env_value: str | None, config_value) -> tuple[str, ...]:
    if env_value:
        return tuple(item.strip() for item in env_value.split(",") if item.strip())
    if config_value:
        return tuple(str(item) for item in config_value)
    return ()


def _default_ddl_paths(root: Path) -> tuple[Path, ...]:
    return (
        root / "resources" / "ddl.sql",
        root / "resources" / "post_schema.sql",
        root / "resources" / "database" / "ddl.sql",
    )
