"""FastAPI routes for framework settings management."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends

from .types import SettingRecord, SettingUpdateRequest


def create_settings_router(
    *,
    get_service: Callable[..., Any],
    get_audit_actor: Callable[..., Any],
    handle_service_error: Callable[[Exception], None],
    service_error_type: type[Exception] = Exception,
) -> APIRouter:
    router = APIRouter(prefix="/settings", tags=["cpkit"])

    @router.get("/")
    async def list_settings(
        service=Depends(get_service),
    ) -> list[SettingRecord]:
        try:
            return service.list_settings()
        except service_error_type as err:
            handle_service_error(err)

    @router.get("/{setting_id}")
    async def get_setting(
        setting_id: str,
        service=Depends(get_service),
    ) -> str:
        try:
            return service.get_setting(setting_id)
        except service_error_type as err:
            handle_service_error(err)

    @router.patch("/{setting_id}")
    async def update_setting(
        setting_id: str,
        request: SettingUpdateRequest,
        actor_id: str = Depends(get_audit_actor),
        service=Depends(get_service),
    ) -> None:
        try:
            service.update_setting(setting_id, request.value, actor_id)
        except service_error_type as err:
            handle_service_error(err)

    @router.put("/{setting_id}/reset")
    async def reset_setting(
        setting_id: str,
        actor_id: str = Depends(get_audit_actor),
        service=Depends(get_service),
    ) -> None:
        try:
            service.reset_setting(setting_id, actor_id)
        except service_error_type as err:
            handle_service_error(err)

    return router
