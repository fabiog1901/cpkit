"""Repository helpers for the framework message queue."""

from typing import Any

from cpkit.db import execute_stmt, fetch_all, fetch_one

from .maintenance import FAIL_ZOMBIE_JOBS_MESSAGE_TYPE
from .types import IntID, Job, JobID, JobStatsResponse, LinkedResourceRef, Task

QUEUE_TABLE = "cpkit.mq"
JOBS_TABLE = "cpkit.jobs"
TASKS_TABLE = "cpkit.tasks"


class QueueRepositoryMixin:
    """Repository mixin for enqueueing framework queue messages."""

    def enqueue_message(
        self,
        msg_type: Any,
        payload: Any | None,
        created_by: str,
        *,
        start_after_seconds: int = 0,
    ) -> None:
        """Enqueue a message to be processed by the framework worker."""
        execute_stmt(
            f"""
            INSERT INTO {QUEUE_TABLE}
                (msg_type, msg_data, created_by, start_after)
            VALUES
                (%s, %s, %s, now() + (%s * INTERVAL '1s'))
            """,
            (
                _message_type_value(msg_type),
                _payload_value(payload),
                created_by,
                start_after_seconds,
            ),
            operation="jobs.enqueue_message",
        )


class QueueJobRepositoryMixin(QueueRepositoryMixin):
    """Repository mixin for enqueueing queue messages backed by job records."""

    def enqueue_command(
        self,
        command_type: Any,
        payload: Any,
        created_by: str,
    ) -> JobID:
        payload_value = _payload_value(payload)
        playbook_version = payload_value.get("playbook_version")
        job_description = {
            key: value for key, value in payload_value.items() if key != "playbook_version"
        }
        command_type_value = _message_type_value(command_type)
        return fetch_one(
            f"""
            WITH
            create_new_job AS (
                INSERT INTO {QUEUE_TABLE}
                    (msg_type, msg_data, created_by)
                VALUES
                    (%s, %s, %s)
                RETURNING msg_id
            )
            INSERT INTO {JOBS_TABLE}
                (job_id, job_type, status, playbook_version, description, created_by)
            VALUES
                ((select msg_id from create_new_job), %s, %s, %s, %s, %s)
            RETURNING job_id AS job_id
            """,
            (
                command_type_value,
                payload_value,
                created_by,
                command_type_value,
                "QUEUED",
                str(playbook_version) if playbook_version is not None else None,
                job_description,
                created_by,
            ),
            JobID,
            operation="jobs.enqueue_command",
        )


class JobsRepositoryMixin:
    """Repository mixin for framework job history, status, and task records."""

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
            )
            or JobStatsResponse(total=0, running=0, queued=0, failed=0)
        )

    def list_jobs(self, groups: list[str], is_admin: bool = False) -> list[Job]:
        return fetch_all(
            f"""
            SELECT *
            FROM {JOBS_TABLE}
            ORDER BY created_at DESC;
            """,
            (),
            Job,
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
        )

    def list_tasks(self, job_id: int) -> list[Task]:
        return fetch_all(
            f"""
            SELECT job_id, task_id,
                created_at, task_name, task_desc
            FROM {TASKS_TABLE}
            WHERE job_id = %s
            ORDER BY task_id DESC
            """,
            (job_id,),
            Task,
        )

    def list_linked_resources(self, job_id: int) -> list[LinkedResourceRef]:
        return []

    def update_job(self, job_id: int, status: str) -> None:
        execute_stmt(
            f"""
            UPDATE {JOBS_TABLE}
            SET status = %s
            WHERE job_id = %s
            """,
            (_message_type_value(status), job_id),
        )

    def set_job_playbook_version(self, job_id: int, playbook_version: str) -> None:
        execute_stmt(
            f"""
            UPDATE {JOBS_TABLE}
            SET playbook_version = %s
            WHERE job_id = %s
            """,
            (playbook_version, job_id),
        )

    def fail_zombie_jobs(self) -> list[IntID]:
        return fetch_all(
            f"""
            WITH
            fail_zombie_jobs AS (
                INSERT INTO {QUEUE_TABLE} (msg_type, start_after)
                VALUES (%s, now() + INTERVAL '300s' + + (random() * INTERVAL '10s')
                RETURNING 1
            )
            UPDATE {JOBS_TABLE}
            SET status = %s
            WHERE status in (%s, %s)
                AND now() > updated_at + INTERVAL '300s'
            RETURNING job_id AS id
            """,
            (FAIL_ZOMBIE_JOBS_MESSAGE_TYPE, "FAILED", "RUNNING", "QUEUED"),
            IntID,
        )

    def create_task(
        self,
        job_id: int,
        task_id: int,
        created_at,
        task_name: str,
        task_desc,
    ) -> None:
        execute_stmt(
            f"""
            INSERT INTO {TASKS_TABLE}
                (job_id, task_id, created_at, task_name, task_desc)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (job_id, task_id, created_at, task_name, task_desc),
        )


def _message_type_value(msg_type: Any) -> str:
    return str(getattr(msg_type, "value", msg_type))


def _payload_value(payload: Any | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    raise TypeError("Queue message payload must be a mapping or Pydantic model.")
