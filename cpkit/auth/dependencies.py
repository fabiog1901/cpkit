"""FastAPI authentication dependency helpers for cpkit apps."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from .claims import claims_groups
from .oidc import OIDCManager

ACCESS_KEY_HEADER_NAME = "X-CP-Access-Key"
SIGNATURE_HEADER_NAME = "X-CP-Signature"
TIMESTAMP_HEADER_NAME = "X-Timestamp"

access_key_scheme = APIKeyHeader(
    name=ACCESS_KEY_HEADER_NAME,
    scheme_name="XAccessKey",
    auto_error=False,
)
signature_scheme = APIKeyHeader(
    name=SIGNATURE_HEADER_NAME,
    scheme_name="XSignature",
    auto_error=False,
)
timestamp_scheme = APIKeyHeader(
    name=TIMESTAMP_HEADER_NAME,
    scheme_name="XTimestamp",
    auto_error=False,
)


@dataclass(frozen=True)
class AuthDependencies:
    """Container for standard cpkit auth dependency callables."""

    require_authenticated: Callable[..., Any]
    require_user: Callable[..., Any]
    require_readonly: Callable[..., Any]
    require_admin: Callable[..., Any]
    get_access_scope: Callable[[dict[str, Any]], tuple[list[str], bool]]
    get_audit_actor: Callable[..., str]


def create_auth_dependencies(
    oidc: OIDCManager,
    *,
    get_repo: Callable[..., Any],
    readonly_roles: tuple[Any, ...],
    user_roles: tuple[Any, ...],
    admin_roles: tuple[Any, ...],
    session_cookie_name: str | None = None,
) -> AuthDependencies:
    """Create the standard auth dependencies for a cpkit FastAPI app."""
    effective_session_cookie_name = session_cookie_name or oidc.session_cookie_name

    async def require_authenticated(
        request: Request,
        repo: Any = Depends(get_repo),
        access_key: str | None = Security(access_key_scheme),
        signature: str | None = Security(signature_scheme),
        timestamp: str | None = Security(timestamp_scheme),
    ) -> dict[str, Any]:
        """Return claims for the current caller, regardless of auth transport."""
        oidc.load_config(repo)
        session_token = (
            request.cookies.get(effective_session_cookie_name)
            if effective_session_cookie_name
            else None
        )
        return await oidc.current_claims(
            request,
            repo,
            session_token=session_token,
            access_key=access_key,
            signature=signature,
            timestamp=timestamp,
        )

    def require_user(
        claims: dict[str, Any] = Security(require_authenticated),
    ) -> dict[str, Any]:
        """Require a role that permits mutating application operations."""
        return oidc.ensure_any_role(claims, *user_roles)

    def require_readonly(
        request: Request,
        claims: dict[str, Any] = Security(require_authenticated),
    ) -> dict[str, Any]:
        """Allow read-only roles on GET and require user roles on writes."""
        if request.method.upper() == "GET":
            return oidc.ensure_any_role(claims, *readonly_roles, *user_roles)
        return oidc.ensure_any_role(claims, *user_roles)

    def require_admin(
        claims: dict[str, Any] = Security(require_authenticated),
    ) -> dict[str, Any]:
        """Require an administrator role."""
        return oidc.ensure_any_role(claims, *admin_roles)

    def get_access_scope(claims: dict[str, Any]) -> tuple[list[str], bool]:
        """Return normalized caller groups plus whether the caller is an admin."""
        if claims.get("auth_disabled"):
            return [], True

        groups_claim_name = str(
            claims.get("_groups_claim_name", oidc.config.groups_claim_name)
        )
        groups = sorted(claims_groups(claims, groups_claim_name))

        effective_roles = (
            claims.get("_role_groups")
            if isinstance(claims.get("_role_groups"), dict)
            else oidc.config.role_groups
        )
        is_admin = any(
            _role_groups_intersect(effective_roles, role, groups)
            for role in admin_roles
        )
        return groups, is_admin

    def get_audit_actor(
        claims: dict[str, Any] = Security(require_authenticated),
    ) -> str:
        """Return the identifier that should be written into audit logs."""
        if claims.get("auth_type") == "api_key":
            return str(claims.get("access_key") or "anonymous")

        username = claims.get(oidc.config.ui_username_claim) or claims.get("sub")
        return str(username or "anonymous")

    return AuthDependencies(
        require_authenticated=require_authenticated,
        require_user=require_user,
        require_readonly=require_readonly,
        require_admin=require_admin,
        get_access_scope=get_access_scope,
        get_audit_actor=get_audit_actor,
    )


def _role_groups_intersect(
    role_groups_by_name: dict[Any, Any],
    role: Any,
    groups: list[str],
) -> bool:
    role_groups = role_groups_by_name.get(role, set()) or role_groups_by_name.get(
        _role_value(role),
        set(),
    )
    return bool(role_groups) and not claims_groups({"groups": role_groups}).isdisjoint(
        groups
    )


def _role_value(role: Any) -> str:
    return str(getattr(role, "value", role))
