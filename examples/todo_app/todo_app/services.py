"""Service layer for the cpkit TODO example."""

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
            return self.repo.create_todo(
                title=request.title.strip(),
                notes=request.notes,
                actor=actor,
            )
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
        return updated

    def delete_todo(self, todo_id: int) -> None:
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

    def enqueue_export(self, request: ExportTodosRequest, actor: str) -> JobID:
        try:
            return self.repo.enqueue_command(
                CommandType.EXPORT_TODOS,
                request.model_dump(),
                actor,
            )
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="TODO export jobs are temporarily unavailable.",
                validation_message="The export job could not be queued with the submitted data.",
                fallback_message="Unable to queue TODO export.",
            ) from err
