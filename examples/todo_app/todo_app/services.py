"""Service layer for the cpkit TODO example."""

from cpkit.audit import log_event
from cpkit.errors import RepositoryError, ServiceNotFoundError, from_repository_error
from cpkit.jobs.types import JobID

from .models import (
    CommandType,
    ExportTodosRequest,
    Todo,
    TodoCreateRequest,
    TodoUpdateRequest,
)


class TodosService:
    def __init__(self, repo) -> None:
        self.repo = repo

    def list_todos(self, *, include_completed: bool = True) -> list[Todo]:
        try:
            return self.repo.list_todos(include_completed=include_completed)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="TODOs are temporarily unavailable.",
                fallback_message="Unable to load TODOs.",
            ) from err

    def create_todo(self, request: TodoCreateRequest, actor: str) -> Todo:
        try:
            todo = self.repo.create_todo(
                title=request.title.strip(),
                notes=request.notes,
                actor=actor,
            )
            log_event(
                self.repo,
                actor,
                "TODO_CREATED",
                {
                    "todo_id": str(todo.todo_id),
                    "title": todo.title,
                    "completed": todo.completed,
                },
            )
            return todo
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="TODOs are temporarily unavailable.",
                validation_message="The TODO could not be created with the submitted data.",
                fallback_message="Unable to create TODO.",
            ) from err

    def update_todo(
        self,
        todo_id: int,
        request: TodoUpdateRequest,
        actor: str,
    ) -> Todo:
        try:
            updated = self.repo.update_todo(
                todo_id,
                title=request.title.strip() if request.title is not None else None,
                notes=request.notes,
                completed=request.completed,
                actor=actor,
            )
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="TODOs are temporarily unavailable.",
                validation_message="The TODO could not be updated with the submitted data.",
                fallback_message=f"Unable to update TODO '{todo_id}'.",
            ) from err
        if updated is None:
            raise ServiceNotFoundError(f"TODO '{todo_id}' was not found.")
        log_event(
            self.repo,
            actor,
            "TODO_UPDATED",
            {
                "todo_id": str(updated.todo_id),
                "title": updated.title,
                "completed": updated.completed,
            },
        )
        return updated

    def delete_todo(self, todo_id: int, actor: str) -> None:
        try:
            deleted = self.repo.delete_todo(todo_id)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="TODOs are temporarily unavailable.",
                fallback_message=f"Unable to delete TODO '{todo_id}'.",
            ) from err
        if not deleted:
            raise ServiceNotFoundError(f"TODO '{todo_id}' was not found.")
        log_event(
            self.repo,
            actor,
            "TODO_DELETED",
            {"todo_id": str(todo_id)},
        )

    def enqueue_export(self, request: ExportTodosRequest, actor: str) -> JobID:
        try:
            job_id = self.repo.enqueue_command(
                CommandType.EXPORT_TODOS,
                request.model_dump(),
                actor,
            )
            log_event(
                self.repo,
                actor,
                "TODO_EXPORT_REQUESTED",
                {
                    "job_id": job_id.job_id,
                    "format": request.format,
                    "include_completed": request.include_completed,
                    "output_dir": request.output_dir,
                },
            )
            return job_id
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="TODO export jobs are temporarily unavailable.",
                validation_message="The export job could not be queued with the submitted data.",
                fallback_message="Unable to queue TODO export.",
            ) from err
