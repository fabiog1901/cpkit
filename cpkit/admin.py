"""Admin router assembly for framework-owned capabilities."""

from collections.abc import Callable, Sequence
from typing import Any

from fastapi import APIRouter

from .auth import create_api_keys_router
from .playbooks import create_playbooks_router
from .settings import create_settings_router


def create_cpkit_admin_router(
    *,
    get_api_keys_service: Callable[..., Any],
    get_settings_service: Callable[..., Any],
    get_playbooks_service: Callable[..., Any],
    get_audit_actor: Callable[..., Any],
    handle_service_error: Callable[[Exception], None],
    service_error_type: type[Exception] = Exception,
    prefix: str = "/admin",
    dependencies: Sequence[Any] | None = None,
) -> APIRouter:
    """Create the standard admin routes provided by cpkit."""
    router = APIRouter(
        prefix=prefix,
        dependencies=list(dependencies or ()),
    )
    router.include_router(
        create_settings_router(
            get_service=get_settings_service,
            get_audit_actor=get_audit_actor,
            handle_service_error=handle_service_error,
            service_error_type=service_error_type,
        )
    )
    router.include_router(
        create_playbooks_router(
            get_service=get_playbooks_service,
            get_audit_actor=get_audit_actor,
            handle_service_error=handle_service_error,
            service_error_type=service_error_type,
        )
    )
    router.include_router(
        create_api_keys_router(
            get_service=get_api_keys_service,
            get_audit_actor=get_audit_actor,
            handle_service_error=handle_service_error,
            service_error_type=service_error_type,
        )
    )
    return router
