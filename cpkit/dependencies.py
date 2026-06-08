"""Application-scoped dependency callables exposed by cpkit."""

from typing import Any

from fastapi import Depends, Request, Security

from .auth import access_key_scheme, signature_scheme, timestamp_scheme
from .repository import get_repo

_active_bundle: Any | None = None


def configure_cpkit_dependencies(bundle: Any) -> None:
    """Install the active cpkit bundle used by exported dependencies."""
    global _active_bundle
    _active_bundle = bundle


async def require_authenticated(
    request: Request,
    repo: Any = Depends(get_repo),
    access_key: str | None = Security(access_key_scheme),
    signature: str | None = Security(signature_scheme),
    timestamp: str | None = Security(timestamp_scheme),
) -> dict[str, Any]:
    """Return claims for the current caller."""
    return await _bundle().require_authenticated(
        request,
        repo,
        access_key,
        signature,
        timestamp,
    )


def require_user(
    claims: dict[str, Any] = Security(require_authenticated),
) -> dict[str, Any]:
    """Require a role that permits mutating application operations."""
    return _bundle().require_user(claims)


def require_readonly(
    request: Request,
    claims: dict[str, Any] = Security(require_authenticated),
) -> dict[str, Any]:
    """Allow read-only roles on GET and require user roles on writes."""
    return _bundle().require_readonly(request, claims)


def require_admin(
    claims: dict[str, Any] = Security(require_authenticated),
) -> dict[str, Any]:
    """Require an administrator role."""
    return _bundle().require_admin(claims)


def get_access_scope(claims: dict[str, Any]) -> tuple[list[str], bool]:
    """Return normalized caller groups plus whether the caller is an admin."""
    return _bundle().get_access_scope(claims)


def get_audit_actor(
    claims: dict[str, Any] = Security(require_authenticated),
) -> str:
    """Return the identifier that should be written into audit logs."""
    return _bundle().get_audit_actor(claims)


def _bundle() -> Any:
    if _active_bundle is None:
        raise RuntimeError("cpkit dependencies are not configured.")
    return _active_bundle
