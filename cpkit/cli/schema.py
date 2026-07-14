"""Database schema and playbook initialization helpers for cpkit applications."""

import gzip
from collections.abc import Sequence
from pathlib import Path

import psycopg

from cpkit.db import close_db, initialize_postgres
from cpkit.db import postgres as postgres_db
from cpkit.repository import CPKitRepo
from cpkit.settings import FrameworkSettingKey
from cpkit.settings.repository import SETTINGS_TABLE
from cpkit.time import STRFTIME

SUPPORTED_PLAYBOOK_EXTENSIONS = {".yaml", ".yml", ".json"}


def apply_sql_file(db_url: str, path: str | Path) -> None:
    """Execute a SQL file against the configured database."""
    sql_path = Path(path)
    sql = sql_path.read_text()
    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)


def check_database(db_url: str) -> None:
    """Verify the database can be reached."""
    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()


def check_table(db_url: str, table_name: str) -> None:
    """Verify a required table can be queried."""
    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
            cur.fetchone()


def disable_oidc(db_url: str, updated_by: str = "cpkit-cli") -> None:
    """Disable OIDC directly in cpkit settings."""
    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {SETTINGS_TABLE}
                SET
                    value = %s,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = %s
                WHERE key = %s
                RETURNING key
                """,
                ("false", updated_by, FrameworkSettingKey.oidc_enabled.value),
            )
            if cur.fetchone() is None:
                raise RuntimeError(
                    f"Required setting '{FrameworkSettingKey.oidc_enabled.value}' "
                    "was not found. Run init first."
                )


def initialize_playbooks(
    db_url: str,
    playbook_dirs: Sequence[str | Path],
) -> None:
    """Initialize default playbooks from app-provided directories."""
    if not playbook_dirs:
        return
    should_close_pool = postgres_db.pool is None
    initialize_postgres(db_url)
    try:
        _initialize_playbooks_from_dirs(playbook_dirs, CPKitRepo())
    finally:
        if should_close_pool:
            close_db()


def _initialize_playbooks_from_dirs(
    playbook_dirs: Sequence[str | Path],
    repo,
) -> None:
    for path in _iter_playbook_files(playbook_dirs):
        _initialize_playbook_file(path, repo)


def _initialize_playbook_file(path: Path, repo) -> None:
    name = path.stem
    content = path.read_text(encoding="utf-8")
    current_playbook = repo.get_default_playbook(name)
    if (
        current_playbook
        and _decode_playbook_content(current_playbook.content) == content
    ):
        if current_playbook.default_version is None:
            repo.set_default_playbook(
                name, current_playbook.version.strftime(STRFTIME), "system"
            )
        return

    if current_playbook:
        repo.delete_playbook(name, current_playbook.version.strftime(STRFTIME))

    saved = repo.create_playbook(
        name,
        gzip.compress(content.encode("utf-8")),
        "system",
    )
    repo.set_default_playbook(name, saved.version.strftime(STRFTIME), "system")


def _iter_playbook_files(
    playbook_dirs: Sequence[str | Path],
) -> list[Path]:
    files: list[Path] = []
    for directory in playbook_dirs:
        root = Path(directory)
        if not root.exists() or not root.is_dir():
            continue
        files.extend(
            path
            for path in sorted(root.iterdir())
            if path.is_file()
            and not path.name.startswith(".")
            and path.suffix.lower() in SUPPORTED_PLAYBOOK_EXTENSIONS
        )
    return files


def _decode_playbook_content(content: bytes | None) -> str | None:
    if content is None:
        return None
    return gzip.decompress(content).decode("utf-8")
