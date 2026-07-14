"""Job handlers for the cpkit TODO example."""

import csv
import datetime as dt
import io
import json

from cpkit import get_repo
from cpkit.playbooks import run_playbook

from .models import CommandType, ExportTodosPayload
from .repos import todo_to_export_row


def export_todos(job_id: int, payload: ExportTodosPayload, created_by: str) -> None:
    repo = get_repo()
    todos = repo.list_todos(include_completed=payload.include_completed)
    rows = [todo_to_export_row(todo) for todo in todos]
    output_path = payload.output_directory / f"todos-{job_id}.{payload.format}"
    result = run_playbook(
        repo=repo,
        job_id=job_id,
        playbook_name="EXPORT_TODOS",
        extra_vars={
            "requested_by": created_by,
            "export_format": payload.format,
            "include_completed": payload.include_completed,
            "output_dir": str(payload.output_directory),
            "output_path": str(output_path),
            "row_count": len(rows),
            "rows": rows,
            "export_json": json.dumps(rows, indent=2),
            "export_csv": _export_csv(rows),
        },
    )
    if result.status != "successful":
        raise RuntimeError(f"Export playbook failed with status {result.status}")
    repo.create_task(
        job_id,
        result.task_id_counter,
        _now(),
        "EXPORT_WRITTEN",
        str(output_path),
    )


def _export_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
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
    return buffer.getvalue()


def _now():
    return dt.datetime.now(dt.timezone.utc)


COMMAND_HANDLERS = {
    CommandType.EXPORT_TODOS: export_todos,
}
