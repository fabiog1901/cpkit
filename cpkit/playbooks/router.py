"""FastAPI routes for framework playbook management."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends

from .types import PlaybookResponse, PlaybookSaveRequest, PlaybookVersionResponse


def create_playbooks_router(
    *,
    get_service: Callable[..., Any],
    get_audit_actor: Callable[..., Any],
    handle_service_error: Callable[[Exception], None],
    service_error_type: type[Exception] = Exception,
) -> APIRouter:
    router = APIRouter(prefix="/playbooks", tags=["cpkit"])

    @router.get("/{name}", response_model=PlaybookResponse)
    async def get_playbook(
        name: str,
        service=Depends(get_service),
    ) -> PlaybookResponse:
        try:
            return service.get_playbook(name)
        except service_error_type as err:
            handle_service_error(err)

    @router.get("/{name}/{version}", response_model=PlaybookVersionResponse)
    async def get_playbook_version(
        name: str,
        version: str,
        service=Depends(get_service),
    ) -> PlaybookVersionResponse:
        try:
            return service.get_playbook_version(name, version)
        except service_error_type as err:
            handle_service_error(err)

    @router.post("/{name}", response_model=PlaybookVersionResponse)
    async def save_playbook(
        name: str,
        request: PlaybookSaveRequest,
        actor_id: str = Depends(get_audit_actor),
        service=Depends(get_service),
    ) -> PlaybookVersionResponse:
        try:
            return service.save_playbook(name, request.content, actor_id)
        except service_error_type as err:
            handle_service_error(err)

    @router.put("/{name}/{version}")
    async def set_default_playbook(
        name: str,
        version: str,
        actor_id: str = Depends(get_audit_actor),
        service=Depends(get_service),
    ) -> None:
        try:
            service.set_default_playbook(name, version, actor_id)
        except service_error_type as err:
            handle_service_error(err)

    @router.delete("/{name}/{version}", response_model=PlaybookVersionResponse)
    async def delete_playbook_version(
        name: str,
        version: str,
        actor_id: str = Depends(get_audit_actor),
        service=Depends(get_service),
    ) -> PlaybookVersionResponse:
        try:
            return service.delete_playbook_version(
                name,
                version,
                actor_id,
            )
        except service_error_type as err:
            handle_service_error(err)

    return router
