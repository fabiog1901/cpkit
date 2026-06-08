"""Bundled authentication wiring for cpkit FastAPI apps."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter

from cpkit.audit import create_audit_event_hook

from .dependencies import AuthDependencies, create_auth_dependencies
from .oidc import OIDCManager
from .router import create_oidc_router
from .secrets import decrypt_secret, encrypt_secret, validate_secret_crypto_config
from .types import OIDCSessionRecord

DEFAULT_OIDC_SESSION_COOKIE_NAME = "cp_session"
DEFAULT_READONLY_ROLES = ("CP_READONLY",)
DEFAULT_USER_ROLES = ("CP_USER", "CP_ADMIN")
DEFAULT_ADMIN_ROLES = ("CP_ADMIN",)


@dataclass(frozen=True)
class AuthBundle:
    """Standard auth objects for a cpkit app."""

    oidc: OIDCManager
    dependencies: AuthDependencies
    router: APIRouter

    @property
    def require_authenticated(self):
        return self.dependencies.require_authenticated

    @property
    def require_user(self):
        return self.dependencies.require_user

    @property
    def require_readonly(self):
        return self.dependencies.require_readonly

    @property
    def require_admin(self):
        return self.dependencies.require_admin

    @property
    def get_access_scope(self):
        return self.dependencies.get_access_scope

    @property
    def get_audit_actor(self):
        return self.dependencies.get_audit_actor


def create_auth_bundle(
    *,
    get_repo: Callable[..., Any],
    audit_record_factory: Callable[..., Any],
    session_cookie_name: str = DEFAULT_OIDC_SESSION_COOKIE_NAME,
    readonly_roles: tuple[Any, ...] = DEFAULT_READONLY_ROLES,
    user_roles: tuple[Any, ...] = DEFAULT_USER_ROLES,
    admin_roles: tuple[Any, ...] = DEFAULT_ADMIN_ROLES,
    login_event: str = "LOGIN",
    logout_event: str = "LOGOUT",
    missing_api_key_headers_detail: str = (
        "X-CP-Access-Key, X-CP-Signature, and X-Timestamp are required."
    ),
) -> AuthBundle:
    """Create standard OIDC/API-key auth for a cpkit application."""
    oidc = OIDCManager(
        encrypt_secret=encrypt_secret,
        decrypt_secret=decrypt_secret,
        session_record_factory=OIDCSessionRecord,
        session_cookie_name=session_cookie_name,
        validate_secret_crypto_config=validate_secret_crypto_config,
        missing_api_key_headers_detail=missing_api_key_headers_detail,
    )
    dependencies = create_auth_dependencies(
        oidc,
        get_repo=get_repo,
        session_cookie_name=session_cookie_name,
        readonly_roles=readonly_roles,
        user_roles=user_roles,
        admin_roles=admin_roles,
    )
    emit_auth_event = create_audit_event_hook(
        audit_record_factory,
        best_effort=False,
    )

    def log_auth_event(
        repo: Any,
        actor_id: str,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        event_type = login_event if action == "LOGIN" else logout_event
        emit_auth_event(
            repo,
            actor_id,
            event_type,
            details,
        )

    router = create_oidc_router(
        oidc,
        get_repo=get_repo,
        require_authenticated=dependencies.require_authenticated,
        get_audit_actor=dependencies.get_audit_actor,
        audit_event_hook=log_auth_event,
    )
    return AuthBundle(oidc=oidc, dependencies=dependencies, router=router)
