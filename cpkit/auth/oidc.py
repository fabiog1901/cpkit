"""Reusable OIDC provider client mechanics."""

import json
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import jwt
from fastapi import HTTPException, status

from .api_keys import APIKeyAuthenticationError, APIKeyAuthenticator
from .claims import claims_groups, jsonable_role_groups
from .config import OIDCConfig


class OIDCAuthenticationError(Exception):
    """Raised when an OIDC token cannot be authenticated."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class OIDCSessionRepository(Protocol):
    """Repository-like object that persists OIDC server-side sessions."""

    def get_oidc_session(self, session_id: str) -> Any | None: ...

    def delete_oidc_session(self, session_id: str) -> None: ...

    def update_oidc_session(
        self,
        session_id: str,
        *,
        encrypted_id_token: bytes,
        encrypted_refresh_token: bytes | None,
        token_expires_at: datetime,
    ) -> None: ...


class OIDCProviderClient:
    """Load OIDC provider metadata and exchange OAuth/OIDC tokens."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self._metadata: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._meta_loaded_at = 0.0
        self._jwks_loaded_at = 0.0
        self._cache_ttl_seconds = getattr(config, "cache_ttl_seconds", 300)

    def update_provider_config(self, config: Any, *, clear_cache: bool = False) -> None:
        self.config = config
        self._cache_ttl_seconds = getattr(config, "cache_ttl_seconds", 300)
        if clear_cache:
            self.clear_provider_cache()

    def clear_provider_cache(self) -> None:
        self._metadata = None
        self._jwks = None
        self._meta_loaded_at = 0.0
        self._jwks_loaded_at = 0.0

    def _http_json(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        req_headers = {"Accept": "application/json"}
        if headers:
            req_headers.update(headers)

        payload = None
        if data is not None:
            payload = urllib.parse.urlencode(data).encode("utf-8")
            req_headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(
            url,
            data=payload,
            headers=req_headers,
            method=method,
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise RuntimeError(f"Expected JSON object from {url}")
            return parsed

    def get_metadata(self) -> dict[str, Any]:
        """Return cached OIDC discovery metadata, refreshing it when needed."""
        if (
            self._metadata
            and (time.time() - self._meta_loaded_at) < self._cache_ttl_seconds
        ):
            return self._metadata
        metadata_url = f"{self.config.issuer_url}/.well-known/openid-configuration"
        self._metadata = self._http_json(metadata_url)
        self._meta_loaded_at = time.time()
        return self._metadata

    def get_jwks(self) -> dict[str, Any]:
        """Return cached provider signing keys, refreshing them when needed."""
        if (
            self._jwks
            and (time.time() - self._jwks_loaded_at) < self._cache_ttl_seconds
        ):
            return self._jwks

        metadata = self.get_metadata()
        jwks_uri = str(metadata.get("jwks_uri") or "")
        if not jwks_uri:
            raise RuntimeError("OIDC provider metadata missing 'jwks_uri'")

        self._jwks = self._http_json(jwks_uri)
        self._jwks_loaded_at = time.time()
        return self._jwks

    def build_authorization_url(self, redirect_uri: str, state: str, nonce: str) -> str:
        """Build the provider authorization URL for starting login."""
        metadata = self.get_metadata()
        auth_endpoint = str(metadata.get("authorization_endpoint") or "")
        if not auth_endpoint:
            raise RuntimeError(
                "OIDC provider metadata missing 'authorization_endpoint'"
            )

        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "scope": self.config.scopes,
            "state": state,
            "nonce": nonce,
        }

        if self.config.audience:
            params["audience"] = self.config.audience

        params.update(self.config.extra_auth_params())

        return f"{auth_endpoint}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange an OIDC authorization code for a token response."""
        metadata = self.get_metadata()
        token_endpoint = str(metadata.get("token_endpoint") or "")
        if not token_endpoint:
            raise RuntimeError("OIDC provider metadata missing 'token_endpoint'")

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "redirect_uri": redirect_uri,
        }
        payload.update(self.config.extra_auth_params())

        return self._http_json(token_endpoint, method="POST", data=payload)

    def refresh_tokens(self, refresh_token: str) -> dict[str, Any]:
        """Exchange a refresh token for fresh token material."""
        metadata = self.get_metadata()
        token_endpoint = str(metadata.get("token_endpoint") or "")
        if not token_endpoint:
            raise RuntimeError("OIDC provider metadata missing 'token_endpoint'")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }

        return self._http_json(token_endpoint, method="POST", data=payload)

    def select_jwk_key(self, token: str) -> Any:
        """Return the provider signing key that matches a JWT header."""
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise OIDCAuthenticationError("Token header is missing 'kid'")

        keys = self.get_jwks().get("keys", [])
        for jwk in keys:
            if jwk.get("kid") == kid:
                return jwt.PyJWK.from_dict(jwk).key

        self._jwks = None
        keys = self.get_jwks().get("keys", [])
        for jwk in keys:
            if jwk.get("kid") == kid:
                return jwt.PyJWK.from_dict(jwk).key

        raise OIDCAuthenticationError("Unable to find a matching JWKS key for token")

    def validate_jwt(
        self,
        token: str,
        *,
        expected_nonce: str | None = None,
        strict_client_audience: bool = False,
    ) -> dict[str, Any]:
        """Validate a JWT against the provider configuration and optional nonce."""
        key = self.select_jwk_key(token)

        options = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_iat": True,
            "verify_nbf": True,
            "verify_iss": True,
            "verify_aud": strict_client_audience
            or self.config.verify_audience
            or bool(self.config.audience),
        }

        audience = None
        if strict_client_audience:
            audience = self.config.client_id
        elif self.config.audience:
            audience = self.config.audience

        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                issuer=self.config.issuer_url,
                audience=audience,
                options=options,
            )
        except jwt.PyJWTError as exc:
            raise OIDCAuthenticationError(f"Invalid token: {exc}") from exc

        if expected_nonce is not None and claims.get("nonce") != expected_nonce:
            raise OIDCAuthenticationError("Invalid token nonce")

        return claims

    @staticmethod
    def token_expires_at(claims: dict[str, Any]) -> datetime:
        """Return the UTC expiration timestamp encoded in JWT claims."""
        raw_exp = claims.get("exp")
        if raw_exp is None:
            raise OIDCAuthenticationError("Token is missing 'exp'.")
        try:
            return datetime.fromtimestamp(float(raw_exp), tz=timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError) as exc:
            raise OIDCAuthenticationError("Token has an invalid 'exp' claim.") from exc


class OIDCSessionManager:
    """Manage encrypted server-side OIDC sessions and token refresh."""

    def __init__(
        self,
        provider_client: OIDCProviderClient,
        *,
        encrypt_secret: Callable[[bytes | str], bytes],
        decrypt_secret: Callable[[bytes | str], bytes],
        session_record_factory: Callable[..., Any],
    ) -> None:
        self.provider_client = provider_client
        self.encrypt_secret = encrypt_secret
        self.decrypt_secret = decrypt_secret
        self.session_record_factory = session_record_factory

    def build_session_record(
        self,
        session_id: str,
        *,
        id_token: str,
        refresh_token: str | None,
        claims: dict[str, Any],
    ) -> Any:
        """Return an encrypted server-side session representation."""
        now = datetime.now(timezone.utc)
        return self.session_record_factory(
            session_id=session_id,
            encrypted_id_token=self.encrypt_secret(id_token),
            encrypted_refresh_token=(
                self.encrypt_secret(refresh_token) if refresh_token else None
            ),
            token_expires_at=OIDCProviderClient.token_expires_at(claims),
            session_expires_at=now
            + timedelta(
                seconds=self.provider_client.config.session_max_age_seconds,
            ),
        )

    def claims_from_session(
        self,
        repo: OIDCSessionRepository,
        session_id: str,
        *,
        authorize_claims: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Load a session and refresh token material when needed."""
        session = repo.get_oidc_session(session_id)
        if session is None:
            raise OIDCAuthenticationError("Not authenticated.")

        now = datetime.now(timezone.utc)
        if session.session_expires_at <= now:
            repo.delete_oidc_session(session_id)
            raise OIDCAuthenticationError("OIDC session expired.")

        refresh_deadline = session.token_expires_at - timedelta(
            seconds=self.provider_client.config.refresh_leeway_seconds
        )
        if refresh_deadline <= now:
            claims = self.refresh_session(
                repo,
                session,
                authorize_claims=authorize_claims,
            )
        else:
            try:
                id_token = self.decrypt_secret(session.encrypted_id_token).decode(
                    "utf-8"
                )
                claims = OIDCProviderClient.validate_jwt(
                    self.provider_client,
                    id_token,
                    strict_client_audience=True,
                )
            except Exception:
                claims = self.refresh_session(
                    repo,
                    session,
                    authorize_claims=authorize_claims,
                )

        claims = authorize_claims(claims)
        claims["_session_id"] = session_id
        claims["auth_type"] = "oidc"
        return claims

    def refresh_session(
        self,
        repo: OIDCSessionRepository,
        session: Any,
        *,
        authorize_claims: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Refresh an OIDC session using its stored refresh token."""
        if not session.encrypted_refresh_token:
            repo.delete_oidc_session(session.session_id)
            raise OIDCAuthenticationError("OIDC session expired.")

        try:
            refresh_token = self.decrypt_secret(session.encrypted_refresh_token).decode(
                "utf-8"
            )
            token_payload = self.provider_client.refresh_tokens(refresh_token)
        except Exception:
            repo.delete_oidc_session(session.session_id)
            raise OIDCAuthenticationError("OIDC refresh failed. Please sign in again.")

        id_token = token_payload.get("id_token")
        if not id_token or not isinstance(id_token, str):
            repo.delete_oidc_session(session.session_id)
            raise OIDCAuthenticationError(
                "OIDC refresh response missing id_token. Please sign in again."
            )

        claims = OIDCProviderClient.validate_jwt(
            self.provider_client,
            id_token,
            strict_client_audience=True,
        )
        authorize_claims(claims)

        next_refresh_token = token_payload.get("refresh_token")
        effective_refresh_token = (
            next_refresh_token
            if isinstance(next_refresh_token, str) and next_refresh_token
            else refresh_token
        )
        repo.update_oidc_session(
            session.session_id,
            encrypted_id_token=self.encrypt_secret(id_token),
            encrypted_refresh_token=self.encrypt_secret(effective_refresh_token),
            token_expires_at=OIDCProviderClient.token_expires_at(claims),
        )
        return claims


class OIDCManager(OIDCProviderClient):
    """Coordinate OIDC config, sessions, API keys, and claim authorization."""

    def __init__(
        self,
        *,
        config: OIDCConfig | None = None,
        encrypt_secret: Callable[[bytes | str], bytes],
        decrypt_secret: Callable[[bytes | str], bytes],
        session_record_factory: Callable[..., Any],
        session_cookie_name: str | None = None,
        missing_api_key_headers_detail: str = (
            "Access key, signature, and timestamp are required."
        ),
        auth_disabled_claims: dict[str, Any] | None = None,
        validate_secret_crypto_config: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(config or OIDCConfig())
        self.sessions = OIDCSessionManager(
            self,
            encrypt_secret=encrypt_secret,
            decrypt_secret=decrypt_secret,
            session_record_factory=session_record_factory,
        )
        self.api_keys = APIKeyAuthenticator(decrypt_secret=decrypt_secret)
        self.session_cookie_name = session_cookie_name
        self.missing_api_key_headers_detail = missing_api_key_headers_detail
        self.auth_disabled_claims = auth_disabled_claims or {
            "sub": "anonymous",
            "auth_disabled": True,
        }
        self.validate_secret_crypto_config = validate_secret_crypto_config
        self._config_loaded_at = 0.0
        self._config_cache_ttl_seconds = 300

    @property
    def enabled(self) -> bool:
        """Expose whether OIDC-backed authentication is enabled."""
        return self.config.enabled

    def load_config(self, repo: Any, *, force: bool = False) -> None:
        """Load framework OIDC configuration from a repository-like object."""
        now = time.time()
        if (
            not force
            and self._config_loaded_at
            and (now - self._config_loaded_at) < self._config_cache_ttl_seconds
        ):
            return

        new_config = OIDCConfig.from_repo(repo)
        self.update_provider_config(
            new_config,
            clear_cache=self.config != new_config,
        )
        self._config_loaded_at = now

    def validate_config(
        self,
        repo: Any,
        *,
        validate_secret_crypto_config: Callable[[], None] | None = None,
    ) -> None:
        """Validate auth configuration at startup."""
        self.load_config(repo, force=True)
        self.config.validate()
        crypto_validator = (
            validate_secret_crypto_config or self.validate_secret_crypto_config
        )
        if crypto_validator is not None:
            crypto_validator()

    def validate_jwt(
        self,
        token: str,
        *,
        expected_nonce: str | None = None,
        strict_client_audience: bool = False,
    ) -> dict[str, Any]:
        """Validate a JWT and translate auth failures into FastAPI errors."""
        try:
            return OIDCProviderClient.validate_jwt(
                self,
                token,
                expected_nonce=expected_nonce,
                strict_client_audience=strict_client_audience,
            )
        except OIDCAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=exc.detail,
            ) from exc

    @staticmethod
    def token_expires_at(claims: dict[str, Any]) -> datetime:
        """Return a JWT expiration timestamp and translate auth failures."""
        try:
            return OIDCProviderClient.token_expires_at(claims)
        except OIDCAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=exc.detail,
            ) from exc

    def build_session_record(
        self,
        session_id: str,
        *,
        id_token: str,
        refresh_token: str | None,
        claims: dict[str, Any],
    ) -> Any:
        """Return the encrypted server-side session representation for a login."""
        return self.sessions.build_session_record(
            session_id,
            id_token=id_token,
            refresh_token=refresh_token,
            claims=claims,
        )

    def ensure_authorized(self, claims: dict[str, Any]) -> dict[str, Any]:
        """Ensure the caller belongs to at least one configured application group."""
        if claims.get("auth_disabled"):
            return claims

        groups_claim_name = str(
            claims.get("_groups_claim_name", self.config.groups_claim_name)
        )
        user_groups = claims_groups(claims, groups_claim_name)
        if not user_groups:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: no groups found in claim '{groups_claim_name}'.",
            )

        if self.config.authorized_groups.isdisjoint(user_groups):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: user is not in any allowed group.",
            )

        return claims

    def enrich_claims(self, claims: dict[str, Any]) -> dict[str, Any]:
        """Add metadata that helps an application render auth state."""
        payload = dict(claims)
        payload["_groups_claim_name"] = str(
            claims.get("_groups_claim_name", self.config.groups_claim_name)
        )
        effective_role_groups = (
            claims.get("_role_groups")
            if isinstance(claims.get("_role_groups"), dict)
            else self.config.role_groups
        )
        payload["_role_groups"] = jsonable_role_groups(effective_role_groups)

        if self.session_cookie_name:
            existing_meta = (
                claims.get("_cp") if isinstance(claims.get("_cp"), dict) else {}
            )
            payload["_cp"] = {
                **existing_meta,
                "display_name_claim": self.config.ui_username_claim,
                "session_cookie_name": self.session_cookie_name,
            }

        return payload

    def ensure_any_role(self, claims: dict[str, Any], *roles: Any) -> dict[str, Any]:
        """Ensure the caller has at least one of the requested application roles."""
        if claims.get("auth_disabled"):
            return claims

        groups_claim_name = str(
            claims.get("_groups_claim_name", self.config.groups_claim_name)
        )
        user_groups = claims_groups(claims, groups_claim_name)
        if not user_groups:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: no groups found in claim '{groups_claim_name}'.",
            )

        effective_roles = (
            claims.get("_role_groups")
            if isinstance(claims.get("_role_groups"), dict)
            else self.config.role_groups
        )
        for role in roles:
            role_name = _role_value(role)
            role_groups = effective_roles.get(role, set()) or effective_roles.get(
                role_name, set()
            )
            if role_groups and not claims_groups(
                {groups_claim_name: role_groups},
                groups_claim_name,
            ).isdisjoint(user_groups):
                return claims

        role_list = ", ".join(_role_value(role) for role in roles)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: requires one of roles [{role_list}].",
        )

    async def validate_api_key(
        self,
        request: Any,
        repo: Any,
        access_key: str,
        signature: str,
        timestamp: str,
    ) -> dict[str, Any]:
        """Authenticate an API request using HMAC-signed API key headers."""
        try:
            return await self.api_keys.authenticate_request(
                request,
                repo,
                access_key=access_key,
                signature=signature,
                timestamp=timestamp,
                max_age_seconds=self.config.api_key_signature_ttl_seconds,
            )
        except APIKeyAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=exc.detail,
            ) from exc

    async def current_claims(
        self,
        request: Any,
        repo: Any,
        *,
        session_token: str | None = None,
        access_key: str | None = None,
        signature: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Resolve request claims from API-key headers or an OIDC session."""
        if access_key or signature or timestamp:
            if not access_key or not signature or not timestamp:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=self.missing_api_key_headers_detail,
                )
            return await self.validate_api_key(
                request,
                repo,
                access_key,
                signature,
                timestamp,
            )

        if not self.enabled:
            return dict(self.auth_disabled_claims)

        if session_token:
            return self.claims_from_session(repo, session_token)

        raise self.not_authenticated_exception()

    def claims_from_session(
        self,
        repo: OIDCSessionRepository,
        session_id: str,
    ) -> dict[str, Any]:
        """Load a server-side OIDC session, refreshing token material when needed."""
        try:
            return self.sessions.claims_from_session(
                repo,
                session_id,
                authorize_claims=self.ensure_authorized,
            )
        except OIDCAuthenticationError as exc:
            raise self.not_authenticated_exception(exc.detail) from exc

    def refresh_session(
        self,
        repo: OIDCSessionRepository,
        session: Any,
    ) -> dict[str, Any]:
        """Refresh an OIDC session using its stored refresh token."""
        try:
            return self.sessions.refresh_session(
                repo,
                session,
                authorize_claims=self.ensure_authorized,
            )
        except OIDCAuthenticationError as exc:
            raise self.not_authenticated_exception(exc.detail) from exc

    def not_authenticated_exception(
        self,
        detail: str = "Not authenticated.",
    ) -> HTTPException:
        """Return the standard unauthenticated exception for OIDC session flows."""
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"X-Auth-Login-Url": self.config.login_path},
        )


def _role_value(role: Any) -> str:
    return str(getattr(role, "value", role))
