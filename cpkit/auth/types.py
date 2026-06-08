"""Generic auth capability data types."""

import datetime as dt
from typing import Any

from pydantic import BaseModel


class ApiKeyRecord(BaseModel):
    access_key: str
    encrypted_secret_access_key: bytes
    owner: str
    valid_until: dt.datetime
    roles: list[Any] | None = None


class ApiKeySummary(BaseModel):
    access_key: str
    owner: str
    valid_until: dt.datetime
    roles: list[Any] | None = None


class ApiKeyCreateRequest(BaseModel):
    valid_until: dt.datetime
    roles: list[Any] | None = None


class ApiKeyCreateRequestInDB(ApiKeyCreateRequest):
    access_key: str


class ApiKeyCreateResponse(ApiKeySummary):
    secret_access_key: str


class OIDCSessionRecord(BaseModel):
    session_id: str
    encrypted_id_token: bytes
    encrypted_refresh_token: bytes | None = None
    token_expires_at: dt.datetime
    session_expires_at: dt.datetime
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class RoleGroupMap(BaseModel):
    role: str
    groups: list[str]
