"""Audit event HTTP routes for cpkit FastAPI apps."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Query

from .types import AuditEventCountResponse, AuditLogRecord


def create_events_router(
    *,
    get_service: Callable[..., Any],
    get_access_scope: Callable[[dict], tuple[list[str], bool]],
    require_readonly: Callable[..., Any],
    handle_service_error: Callable[[Exception], None],
    service_error_type: type[Exception] = Exception,
) -> APIRouter:
    """Create the framework audit event read routes."""
    router = APIRouter(prefix="/events", tags=["cpkit"])

    @router.get("/")
    async def list_events(
        limit: int = Query(default=20, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        claims: dict = Depends(require_readonly),
        service=Depends(get_service),
    ) -> list[AuditLogRecord]:
        groups, is_admin = get_access_scope(claims)
        try:
            return service.list_visible_events(limit, offset, groups, is_admin)
        except service_error_type as err:
            handle_service_error(err)

    @router.get("/count", response_model=AuditEventCountResponse)
    async def get_event_count(
        service=Depends(get_service),
    ) -> AuditEventCountResponse:
        try:
            total = service.get_event_total()
        except service_error_type as err:
            handle_service_error(err)

        return AuditEventCountResponse(total=total)

    return router
