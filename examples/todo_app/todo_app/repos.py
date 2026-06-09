"""Repository layer for the cpkit TODO example."""

from typing import Any

from cpkit.audit.types import AuditLogRecord
from cpkit.db import execute_stmt, fetch_all, fetch_one, fetch_scalar
from cpkit.jobs.types import Job, JobStatsResponse
from cpkit.repository import CPKitRepo

from .models import Todo

TODOS_TABLE = "todos"
JOBS_TABLE = "cpkit.jobs"
EVENT_LOG_TABLE = "cpkit.event_log"


class Repo(CPKitRepo):
    """Application repository that extends the cpkit base repository."""

    def __init__(self, pool) -> None:
        self.pool = pool

    def list_todos(self, *, include_completed: bool = True) -> list[Todo]:
        if include_completed:
            return fetch_all(
                f"""
                SELECT *
                FROM {TODOS_TABLE}
                ORDER BY completed ASC, created_at DESC
                """,
                (),
                Todo,
                operation="todos.list",
            )
        return fetch_all(
            f"""
            SELECT *
            FROM {TODOS_TABLE}
            WHERE completed = false
            ORDER BY created_at DESC
            """,
            (),
            Todo,
            operation="todos.list_open",
        )

    def get_todo(self, todo_id: int) -> Todo | None:
        return fetch_one(
            f"""
            SELECT *
            FROM {TODOS_TABLE}
            WHERE todo_id = %s
            """,
            (todo_id,),
            Todo,
            operation="todos.get",
        )

    def create_todo(self, *, title: str, notes: str | None, actor: str) -> Todo:
        return fetch_one(
            f"""
            INSERT INTO {TODOS_TABLE} (title, notes, created_by, updated_by)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (title, notes, actor, actor),
            Todo,
            operation="todos.create",
        )

    def update_todo(
        self,
        todo_id: int,
        *,
        title: str | None,
        notes: str | None,
        completed: bool | None,
        actor: str,
    ) -> Todo | None:
        existing = self.get_todo(todo_id)
        if existing is None:
            return None

        return fetch_one(
            f"""
            UPDATE {TODOS_TABLE}
            SET
                title = %s,
                notes = %s,
                completed = %s,
                updated_by = %s
            WHERE todo_id = %s
            RETURNING *
            """,
            (
                title if title is not None else existing.title,
                notes if notes is not None else existing.notes,
                completed if completed is not None else existing.completed,
                actor,
                todo_id,
            ),
            Todo,
            operation="todos.update",
        )

    def delete_todo(self, todo_id: int) -> bool:
        existing = self.get_todo(todo_id)
        if existing is None:
            return False
        execute_stmt(
            f"""
            DELETE FROM {TODOS_TABLE}
            WHERE todo_id = %s
            """,
            (todo_id,),
            operation="todos.delete",
        )
        return True

    def get_job_stats(
        self,
        groups: list[str],
        is_admin: bool = False,
    ) -> JobStatsResponse:
        return (
            fetch_one(
                f"""
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(CASE WHEN status = %s THEN 1 ELSE 0 END), 0) AS running,
                    COALESCE(SUM(CASE WHEN status = %s THEN 1 ELSE 0 END), 0) AS queued,
                    COALESCE(SUM(CASE WHEN status = %s THEN 1 ELSE 0 END), 0) AS failed
                FROM {JOBS_TABLE}
                """,
                ("RUNNING", "QUEUED", "FAILED"),
                JobStatsResponse,
                operation="todos.jobs.stats",
            )
            or JobStatsResponse(total=0, running=0, queued=0, failed=0)
        )

    def list_jobs(self, groups: list[str], is_admin: bool = False) -> list[Job]:
        return fetch_all(
            f"""
            SELECT *
            FROM {JOBS_TABLE}
            ORDER BY created_at DESC
            """,
            (),
            Job,
            operation="todos.jobs.list",
        )

    def get_job(
        self,
        job_id: int,
        groups: list[str],
        is_admin: bool = False,
    ) -> Job | None:
        return fetch_one(
            f"""
            SELECT *
            FROM {JOBS_TABLE}
            WHERE job_id = %s
            """,
            (job_id,),
            Job,
            operation="todos.jobs.get",
        )

    def list_events(
        self,
        limit: int,
        offset: int,
        groups: list[str] | None = None,
        is_admin: bool = False,
    ) -> list[AuditLogRecord]:
        return fetch_all(
            f"""
            SELECT ts, user_id, action, details, request_id::TEXT
            FROM {EVENT_LOG_TABLE}
            ORDER BY ts DESC
            LIMIT %s
            OFFSET %s
            """,
            (limit, offset),
            AuditLogRecord,
            operation="todos.events.list",
        )

    def get_event_count(self) -> int:
        return fetch_scalar(
            f"""
            SELECT count(*) AS id
            FROM {EVENT_LOG_TABLE}
            """,
            (),
            operation="todos.events.count",
        )

    @property
    def job_cluster_map_table(self) -> str:
        return ""


def todo_to_export_row(todo: Todo) -> dict[str, Any]:
    return {
        "todo_id": str(todo.todo_id),
        "title": todo.title,
        "notes": todo.notes,
        "completed": todo.completed,
        "created_at": todo.created_at.isoformat(),
        "created_by": todo.created_by,
        "updated_at": todo.updated_at.isoformat(),
        "updated_by": todo.updated_by,
    }
