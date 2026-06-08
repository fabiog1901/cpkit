"""OIDC HTTP routes for cpkit FastAPI apps."""

import secrets
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.responses import RedirectResponse

from .oidc import OIDCManager
from .redirects import safe_next_path

OIDC_STATE_COOKIE_NAME = "cp_oidc_state"
OIDC_NONCE_COOKIE_NAME = "cp_oidc_nonce"
OIDC_NEXT_COOKIE_NAME = "cp_oidc_next"

AuthEventHook = Callable[[Any, str, str, dict[str, Any] | None], None]


def create_oidc_router(
    oidc: OIDCManager,
    *,
    get_repo: Callable[..., Any],
    require_authenticated: Callable[..., Any],
    get_audit_actor: Callable[..., str],
    audit_event_hook: AuthEventHook | None = None,
    prefix: str = "/auth",
    tags: list[str] | None = None,
    state_cookie_name: str = OIDC_STATE_COOKIE_NAME,
    nonce_cookie_name: str = OIDC_NONCE_COOKIE_NAME,
    next_cookie_name: str = OIDC_NEXT_COOKIE_NAME,
) -> APIRouter:
    """Create the standard OIDC auth router for a cpkit app."""
    router = APIRouter(prefix=prefix, tags=tags or ["cpkit"])

    def oidc_cookie_kwargs() -> dict[str, Any]:
        return {
            "httponly": True,
            "secure": oidc.config.cookie_secure,
            "samesite": oidc.config.cookie_samesite,
            "domain": oidc.config.cookie_domain,
            "path": "/",
        }

    def log_auth_event(
        repo: Any,
        actor_id: str,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if audit_event_hook is not None:
            audit_event_hook(repo, actor_id, action, details)

    @router.get("/login")
    def oidc_login(
        request: Request,
        next: str = "/",  # noqa: A002
        repo: Any = Depends(get_repo),
    ):
        """Start the browser OIDC login flow and store anti-CSRF cookies."""
        oidc.load_config(repo)
        if not oidc.enabled:
            raise HTTPException(
                status_code=404,
                detail="OIDC is disabled.",
            )

        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        next_path = safe_next_path(next)
        redirect_uri = oidc.config.redirect_uri or str(request.url_for("oidc_callback"))
        auth_url = oidc.build_authorization_url(redirect_uri, state, nonce)

        resp = RedirectResponse(auth_url, status_code=302)
        cookie_kwargs = oidc_cookie_kwargs()
        resp.set_cookie(state_cookie_name, state, max_age=300, **cookie_kwargs)
        resp.set_cookie(nonce_cookie_name, nonce, max_age=300, **cookie_kwargs)
        resp.set_cookie(next_cookie_name, next_path, max_age=300, **cookie_kwargs)
        return resp

    @router.get("/callback", name="oidc_callback")
    def oidc_callback(
        request: Request,
        repo: Any = Depends(get_repo),
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        error_description: str | None = None,
    ):
        """Finish OIDC login, persist a session, and set the session cookie."""
        oidc.load_config(repo)
        if not oidc.enabled:
            raise HTTPException(
                status_code=404,
                detail="OIDC is disabled.",
            )

        if error:
            desc = error_description or "OIDC authorization failed."
            raise HTTPException(status_code=401, detail=f"{error}: {desc}")

        expected_state = request.cookies.get(state_cookie_name)
        expected_nonce = request.cookies.get(nonce_cookie_name)
        next_path = safe_next_path(request.cookies.get(next_cookie_name))

        if not code:
            raise HTTPException(status_code=400, detail="Missing authorization code.")
        if not state or not expected_state or state != expected_state:
            raise HTTPException(status_code=401, detail="Invalid OIDC state.")
        if not expected_nonce:
            raise HTTPException(status_code=401, detail="Missing OIDC nonce.")

        redirect_uri = oidc.config.redirect_uri or str(request.url_for("oidc_callback"))
        token_payload = oidc.exchange_code(code, redirect_uri)

        id_token = token_payload.get("id_token")
        if not id_token or not isinstance(id_token, str):
            raise HTTPException(
                status_code=401,
                detail="Token endpoint response missing id_token.",
            )
        refresh_token = token_payload.get("refresh_token")
        refresh_token_value = (
            refresh_token if isinstance(refresh_token, str) and refresh_token else None
        )

        claims = oidc.validate_jwt(
            id_token,
            expected_nonce=expected_nonce,
            strict_client_audience=True,
        )
        oidc.ensure_authorized(claims)
        session_id = secrets.token_urlsafe(32)
        repo.create_oidc_session(
            oidc.build_session_record(
                session_id,
                id_token=id_token,
                refresh_token=refresh_token_value,
                claims=claims,
            )
        )
        actor_id = str(claims.get(oidc.config.ui_username_claim) or claims.get("sub"))
        log_auth_event(
            repo,
            actor_id,
            "LOGIN",
            {
                "auth_type": "oidc",
                "refresh_token_present": bool(refresh_token_value),
            },
        )

        resp = RedirectResponse(next_path, status_code=302)
        cookie_kwargs = oidc_cookie_kwargs()
        if oidc.session_cookie_name:
            resp.set_cookie(
                oidc.session_cookie_name,
                session_id,
                max_age=oidc.config.session_max_age_seconds,
                **cookie_kwargs,
            )
        resp.delete_cookie(
            state_cookie_name,
            path="/",
            domain=oidc.config.cookie_domain,
        )
        resp.delete_cookie(
            nonce_cookie_name,
            path="/",
            domain=oidc.config.cookie_domain,
        )
        resp.delete_cookie(
            next_cookie_name,
            path="/",
            domain=oidc.config.cookie_domain,
        )
        return resp

    @router.post("/logout")
    def oidc_logout(
        repo: Any = Depends(get_repo),
        actor_id: str = Depends(get_audit_actor),
        claims: dict[str, Any] = Security(require_authenticated),
    ):
        """Clear the OIDC session cookie and write a logout audit event."""
        session_id = str(claims.get("_session_id") or "").strip()
        if session_id:
            repo.delete_oidc_session(session_id)
        log_auth_event(
            repo,
            actor_id,
            "LOGOUT",
            {"auth_type": str(claims.get("auth_type") or "oidc")},
        )
        resp = Response(status_code=204)
        if oidc.session_cookie_name:
            resp.delete_cookie(
                oidc.session_cookie_name,
                path="/",
                domain=oidc.config.cookie_domain,
            )
        return resp

    @router.get("/me")
    def oidc_me(
        request: Request,
        claims: dict[str, Any] = Security(require_authenticated),
    ) -> dict[str, Any]:
        """Return the current caller's claims plus auth metadata."""
        payload = oidc.enrich_claims(claims)
        payload["cookies"] = request.cookies
        return payload

    return router
