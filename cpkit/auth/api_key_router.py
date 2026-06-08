"""FastAPI routes for framework API-key management."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends

from .types import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeySummary


def create_api_keys_router(
    *,
    get_service: Callable[..., Any],
    get_audit_actor: Callable[..., Any],
    handle_service_error: Callable[[Exception], None],
    service_error_type: type[Exception] = Exception,
) -> APIRouter:
    router = APIRouter(prefix="/api_keys", tags=["cpkit"])

    @router.get("/")
    async def list_api_keys(
        access_key: str | None = None,
        service=Depends(get_service),
    ) -> list[ApiKeySummary]:
        try:
            return service.list_api_keys(access_key)
        except service_error_type as err:
            handle_service_error(err)

    @router.post("/", response_model=ApiKeyCreateResponse)
    async def create_api_key(
        request: ApiKeyCreateRequest,
        actor_id: str = Depends(get_audit_actor),
        service=Depends(get_service),
    ) -> ApiKeyCreateResponse:
        try:
            return service.create_api_key(actor_id, request)
        except service_error_type as err:
            handle_service_error(err)

    @router.delete("/{access_key}")
    async def delete_api_key(
        access_key: str,
        actor_id: str = Depends(get_audit_actor),
        service=Depends(get_service),
    ) -> None:
        try:
            service.delete_api_key(actor_id, access_key)
        except service_error_type as err:
            handle_service_error(err)

    return router
