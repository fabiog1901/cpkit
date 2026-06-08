"""Service helpers for framework API-key management."""

import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from cpkit.errors import (
    RepositoryError,
    ServiceNotFoundError,
    ServiceValidationError,
    from_repository_error,
)

from .secrets import encrypt_secret
from .types import (
    ApiKeyCreateRequest,
    ApiKeyCreateRequestInDB,
    ApiKeyCreateResponse,
    ApiKeySummary,
)

APIKeyAuditHook = Callable[[Any, str, str, dict[str, Any]], None]


class ApiKeysService:
    def __init__(
        self,
        repo,
        *,
        created_hook: APIKeyAuditHook | None = None,
        deleted_hook: APIKeyAuditHook | None = None,
    ) -> None:
        self.repo = repo
        self.created_hook = created_hook
        self.deleted_hook = deleted_hook

    def list_api_keys(self, access_key: str | None = None) -> list[ApiKeySummary]:
        try:
            return self.repo.list_api_keys(access_key)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="API keys are temporarily unavailable.",
                fallback_message="Unable to load API keys.",
            ) from err

    def create_api_key(
        self,
        actor_id: str,
        request: ApiKeyCreateRequest,
    ) -> ApiKeyCreateResponse:
        valid_until = self._normalize_valid_until(request.valid_until)

        if valid_until <= datetime.now(timezone.utc):
            raise ServiceValidationError("valid_until must be in the future.")

        secret_access_key = secrets.token_urlsafe(32)
        access_key = "cp-" + secrets.token_urlsafe(16)

        try:
            created = self.repo.create_api_key(
                ApiKeyCreateRequestInDB(
                    access_key=access_key,
                    valid_until=valid_until,
                    roles=request.roles,
                ),
                owner=actor_id,
                encrypted_secret_access_key=encrypt_secret(secret_access_key),
            )
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="API keys could not be created right now.",
                conflict_message="That API key already exists.",
                validation_message="The API key request is invalid.",
                fallback_message="Unable to create API key.",
            ) from err

        if self.created_hook is not None:
            self.created_hook(
                self.repo,
                actor_id,
                "API_KEY_CREATED",
                {
                    "access_key": created.access_key,
                    "valid_until": created.valid_until.isoformat(),
                    "roles": [_role_value(role) for role in created.roles or []],
                },
            )

        return ApiKeyCreateResponse(
            access_key=created.access_key,
            owner=created.owner,
            valid_until=created.valid_until,
            roles=created.roles,
            secret_access_key=secret_access_key,
        )

    def delete_api_key(self, actor_id: str, access_key: str) -> None:
        try:
            existing_key = self.repo.get_api_key(access_key)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="API keys could not be updated right now.",
                fallback_message=f"Unable to load API key '{access_key}'.",
            ) from err

        if existing_key is None:
            raise ServiceNotFoundError("API key not found.")

        try:
            self.repo.delete_api_key(access_key)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="API keys could not be updated right now.",
                fallback_message=f"Unable to delete API key '{access_key}'.",
            ) from err

        if self.deleted_hook is not None:
            self.deleted_hook(
                self.repo,
                actor_id,
                "API_KEY_DELETED",
                {
                    "access_key": existing_key.access_key,
                    "owner": existing_key.owner,
                    "valid_until": existing_key.valid_until.isoformat(),
                    "roles": [_role_value(role) for role in existing_key.roles or []],
                },
            )

    @staticmethod
    def _normalize_valid_until(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _role_value(role: Any) -> str:
    return str(getattr(role, "value", role))
