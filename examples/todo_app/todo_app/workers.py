"""Job handlers for the cpkit TODO example."""

import csv
import datetime as dt
import json
from pathlib import Path

from cpkit import get_repo

from .models import CommandType, ExportTodosPayload
from .repos import todo_to_export_row


def export_todos(job_id: int, payload: ExportTodosPayload, created_by: str) -> None:
    repo = get_repo()
    repo.update_job(job_id, "RUNNING")
    repo.create_task(job_id, 1, _now(), "EXPORT_STARTED", f"Requested by {created_by}")
    try:
        todos = repo.list_todos(include_completed=payload.include_completed)
        rows = [todo_to_export_row(todo) for todo in todos]
        output_path = _write_export(job_id, payload, rows)
        repo.create_task(job_id, 2, _now(), "EXPORT_WRITTEN", str(output_path))
        repo.update_job(job_id, "COMPLETED")
    except Exception as err:
        repo.create_task(job_id, 99, _now(), "EXPORT_FAILED", str(err))
        repo.update_job(job_id, "FAILED")
        raise


def _write_export(
    job_id: int,
    payload: ExportTodosPayload,
    rows: list[dict],
) -> Path:
    output_dir = payload.output_directory
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"todos-{job_id}.{payload.format}"
    if payload.format == "csv":
        with output_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "todo_id",
                    "title",
                    "notes",
                    "completed",
                    "created_at",
                    "created_by",
                    "updated_at",
                    "updated_by",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)
        return output_path

    output_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return output_path


def _now():
    return dt.datetime.now(dt.timezone.utc)


COMMAND_HANDLERS = {
    CommandType.EXPORT_TODOS: export_todos,
}
