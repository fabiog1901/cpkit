"""FastAPI router for the cpkit TODO example."""

from fastapi import APIRouter, Depends, Security

from cpkit import get_audit_actor, get_repo, require_readonly, require_user
from cpkit.errors import ServiceError, raise_http_from_service_error
from cpkit.jobs.types import JobID

from .models import ExportTodosRequest, Todo, TodoCreateRequest, TodoUpdateRequest
from .services import TodosService

router = APIRouter(prefix="/todos", tags=["todo"])


def get_todos_service() -> TodosService:
    return TodosService(get_repo())


@router.get("/")
async def list_todos(
    include_completed: bool = True,
    _claims: dict = Security(require_readonly),
    service: TodosService = Depends(get_todos_service),
) -> list[Todo]:
    try:
        return service.list_todos(include_completed=include_completed)
    except ServiceError as err:
        raise_http_from_service_error(err)


@router.post("/")
async def create_todo(
    request: TodoCreateRequest,
    _claims: dict = Security(require_user),
    actor: str = Depends(get_audit_actor),
    service: TodosService = Depends(get_todos_service),
) -> Todo:
    try:
        return service.create_todo(request, actor)
    except ServiceError as err:
        raise_http_from_service_error(err)


@router.patch("/{todo_id}")
async def update_todo(
    todo_id: int,
    request: TodoUpdateRequest,
    _claims: dict = Security(require_user),
    actor: str = Depends(get_audit_actor),
    service: TodosService = Depends(get_todos_service),
) -> Todo:
    try:
        return service.update_todo(todo_id, request, actor)
    except ServiceError as err:
        raise_http_from_service_error(err)


@router.delete("/{todo_id}")
async def delete_todo(
    todo_id: int,
    _claims: dict = Security(require_user),
    service: TodosService = Depends(get_todos_service),
) -> None:
    try:
        service.delete_todo(todo_id)
    except ServiceError as err:
        raise_http_from_service_error(err)


@router.post("/export")
async def export_todos(
    request: ExportTodosRequest,
    _claims: dict = Security(require_user),
    actor: str = Depends(get_audit_actor),
    service: TodosService = Depends(get_todos_service),
) -> JobID:
    try:
        return service.enqueue_export(request, actor)
    except ServiceError as err:
        raise_http_from_service_error(err)
