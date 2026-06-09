"""Database migration and preflight helpers for cpkit applications."""

from pathlib import Path

import psycopg


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
