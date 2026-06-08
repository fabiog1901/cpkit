"""Low-level Postgres metadata database infrastructure."""

import logging
import os
from typing import Any

from psycopg import DatabaseError, InterfaceError, OperationalError
from psycopg import errors as psycopg_errors
from psycopg.abc import Dumper
from psycopg.pq import Format
from psycopg.rows import class_row
from psycopg.types.array import ListDumper
from psycopg.types.json import Jsonb, JsonbDumper
from psycopg_pool import ConnectionPool

from cpkit.errors import (
    RepositoryConflictError,
    RepositoryError,
    RepositoryPermissionError,
    RepositoryUnavailableError,
    RepositoryValidationError,
)

DB_URL = os.getenv("DB_URL")
pool: ConnectionPool | None = None
logger = logging.getLogger(__name__)


class Dict2JsonbDumper(JsonbDumper):
    def dump(self, obj):
        return super().dump(Jsonb(obj))


class SelectorDumper(Dumper):
    """Choose the correct dumper for list payloads."""

    format = Format.BINARY
    oid = None

    _dict_dumper = Dict2JsonbDumper(list)
    _list_dumper = ListDumper(list)

    def upgrade(self, obj, format: Format) -> Dumper:
        if obj and isinstance(obj[0], dict):
            return self._dict_dumper
        return self._list_dumper


def execute_stmt(
    stmt: str,
    bind_args: tuple = (),
    *,
    operation: str | None = None,
) -> None:
    with get_pool().connection() as conn:
        _register_dumpers(conn)

        with conn.cursor() as cur:
            try:
                stmt = _normalize_stmt(stmt)
                cur.execute(stmt, bind_args)
            except Exception as err:
                raise translate_database_error(err, operation) from err


def fetch_all(
    stmt: str,
    bind_args: tuple,
    row_type,
    *,
    operation: str | None = None,
) -> list[Any]:
    with get_pool().connection() as conn:
        _register_dumpers(conn)

        with conn.cursor(row_factory=class_row(row_type)) as cur:
            try:
                stmt = _normalize_stmt(stmt)
                cur.execute(stmt, bind_args)
                return cur.fetchall()
            except Exception as err:
                raise translate_database_error(err, operation) from err


def fetch_one(
    stmt: str,
    bind_args: tuple,
    row_type,
    *,
    operation: str | None = None,
) -> Any | None:
    with get_pool().connection() as conn:
        _register_dumpers(conn)

        with conn.cursor(row_factory=class_row(row_type)) as cur:
            try:
                stmt = _normalize_stmt(stmt)
                cur.execute(stmt, bind_args)
                return cur.fetchone()
            except Exception as err:
                raise translate_database_error(err, operation) from err


def fetch_scalar(
    stmt: str,
    bind_args: tuple = (),
    *,
    operation: str | None = None,
) -> Any | None:
    with get_pool().connection() as conn:
        _register_dumpers(conn)

        with conn.cursor() as cur:
            try:
                stmt = _normalize_stmt(stmt)
                cur.execute(stmt, bind_args)
                row = cur.fetchone()
                if row is None:
                    return None
                return row[0]
            except Exception as err:
                raise translate_database_error(err, operation) from err


def _register_dumpers(conn) -> None:
    conn.adapters.register_dumper(set, ListDumper)
    conn.adapters.register_dumper(dict, Dict2JsonbDumper)
    conn.adapters.register_dumper(list, SelectorDumper)


def _normalize_stmt(stmt: str) -> str:
    return " ".join([s.strip() for s in stmt.split("\n")])


def initialize_postgres(db_url: str | None = None) -> None:
    global pool

    effective_db_url = db_url or DB_URL
    if not effective_db_url:
        raise EnvironmentError("DB_URL env variable not found!")

    if pool is not None:
        return

    pool = ConnectionPool(
        effective_db_url,
        kwargs={"autocommit": True},
        configure=_register_dumpers,
    )


def get_pool() -> ConnectionPool:
    if pool is None:
        raise RuntimeError("Database pool not initialized. Ensure lifespan ran.")
    return pool


def close_db() -> None:
    global pool

    if pool is not None:
        pool.close()

    pool = None


def translate_database_error(
    err: Exception,
    operation: str | None,
    *,
    unavailable_error_types: tuple[type[Exception], ...] = (),
) -> RepositoryError:
    operation_name = operation or "database.statement"
    sqlstate = getattr(err, "sqlstate", None)

    if unavailable_error_types and isinstance(err, unavailable_error_types):
        logger.warning(
            "Database unavailable [operation=%s error=%s reason=%s]",
            operation_name,
            err.__class__.__name__,
            getattr(err, "reason", str(err)),
        )
        return RepositoryUnavailableError(
            "Database is temporarily unavailable.",
            operation=operation_name,
            retryable=True,
        )

    logger.exception(
        "Database operation failed [operation=%s sqlstate=%s error=%s]",
        operation_name,
        sqlstate,
        err.__class__.__name__,
    )

    if isinstance(
        err,
        (
            OperationalError,
            InterfaceError,
            psycopg_errors.SerializationFailure,
            psycopg_errors.DeadlockDetected,
        ),
    ):
        return RepositoryUnavailableError(
            "Database is temporarily unavailable.",
            operation=operation_name,
            retryable=True,
        )

    if isinstance(err, psycopg_errors.UniqueViolation):
        return RepositoryConflictError(
            "Database write conflicts with existing data.",
            operation=operation_name,
        )

    if isinstance(err, psycopg_errors.DuplicateDatabase):
        return RepositoryConflictError(
            "Database already exists.",
            operation=operation_name,
        )

    if isinstance(
        err,
        (
            psycopg_errors.ForeignKeyViolation,
            psycopg_errors.CheckViolation,
            psycopg_errors.NotNullViolation,
            psycopg_errors.InvalidTextRepresentation,
        ),
    ):
        return RepositoryValidationError(
            "Database rejected invalid data.",
            operation=operation_name,
        )

    if isinstance(err, psycopg_errors.InsufficientPrivilege):
        return RepositoryPermissionError(
            "Database permission denied.",
            operation=operation_name,
        )

    if isinstance(err, DatabaseError):
        return RepositoryError(
            "Database operation failed.",
            operation=operation_name,
        )

    return RepositoryError(
        "Repository operation failed.",
        operation=operation_name,
    )
