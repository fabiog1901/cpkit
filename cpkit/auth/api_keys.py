"""Reusable API-key request signing helpers."""

from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from typing import Any, Protocol


class APIKeyAuthenticationError(Exception):
    """Raised when an API key request cannot be authenticated."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class APIKeyRepository(Protocol):
    """Repository-like object that can fetch API key records."""

    def get_api_key(self, access_key: str) -> Any | None: ...


def parse_api_key_timestamp(timestamp: str) -> datetime:
    """Parse either epoch seconds or an ISO-8601 timestamp into UTC."""
    raw_timestamp = timestamp.strip()
    if not raw_timestamp:
        raise ValueError("empty timestamp")

    try:
        parsed = datetime.fromtimestamp(float(raw_timestamp), tz=timezone.utc)
    except OSError, OverflowError, ValueError:
        normalized = (
            f"{raw_timestamp[:-1]}+00:00"
            if raw_timestamp.endswith("Z")
            else raw_timestamp
        )
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)

    return parsed


def request_target_bytes(request: Any) -> bytes:
    """Return the exact path and query bytes covered by the request signature."""
    raw_path = request.scope.get("raw_path")
    if isinstance(raw_path, bytes) and raw_path:
        path = raw_path
    else:
        path = request.url.path.encode("utf-8")

    query_string = request.scope.get("query_string")
    if isinstance(query_string, bytes) and query_string:
        return path + b"?" + query_string
    return path


def build_api_key_signature_payload(
    request: Any,
    timestamp: str,
    body: bytes,
) -> bytes:
    """Build the canonical payload used for HMAC request signing."""
    return b"\n".join(
        [
            request.method.upper().encode("utf-8"),
            request_target_bytes(request),
            timestamp.strip().encode("utf-8"),
            body,
        ]
    )


def api_key_signature(
    secret_key: bytes,
    request: Any,
    timestamp: str,
    body: bytes,
) -> str:
    """Return the expected HMAC signature for an API-key-authenticated request."""
    return hmac_new(
        secret_key,
        build_api_key_signature_payload(request, timestamp, body),
        sha256,
    ).hexdigest()


class APIKeyAuthenticator:
    """Authenticate HMAC-signed API key requests."""

    def __init__(self, *, decrypt_secret) -> None:
        self.decrypt_secret = decrypt_secret

    async def authenticate_request(
        self,
        request: Any,
        repo: APIKeyRepository,
        *,
        access_key: str,
        signature: str,
        timestamp: str,
        max_age_seconds: int,
    ) -> dict[str, Any]:
        api_key = repo.get_api_key(access_key)
        if api_key is None:
            raise APIKeyAuthenticationError("Invalid API key.")

        if datetime.now(timezone.utc) >= api_key.valid_until:
            raise APIKeyAuthenticationError("API key is expired.")

        try:
            signed_at = parse_api_key_timestamp(timestamp)
        except ValueError as exc:
            raise APIKeyAuthenticationError("Invalid X-Timestamp header.") from exc

        age_seconds = abs((datetime.now(timezone.utc) - signed_at).total_seconds())
        if age_seconds > max_age_seconds:
            raise APIKeyAuthenticationError("API request timestamp is expired.")

        body = await request.body()
        secret_key = self.decrypt_secret(api_key.encrypted_secret_access_key)
        expected_signature = api_key_signature(secret_key, request, timestamp, body)

        if not compare_digest(expected_signature, signature.strip().lower()):
            raise APIKeyAuthenticationError("Invalid API key signature.")

        roles = set(api_key.roles or [])
        role_groups = {role: {_role_value(role)} for role in roles}
        return {
            "sub": api_key.owner,
            "access_key": api_key.access_key,
            "groups": [_role_value(role) for role in roles],
            "_groups_claim_name": "groups",
            "_role_groups": role_groups,
            "auth_type": "api_key",
        }


def _role_value(role: Any) -> str:
    return str(getattr(role, "value", role))
