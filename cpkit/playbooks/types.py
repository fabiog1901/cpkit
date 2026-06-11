"""Generic playbook data types."""

import datetime as dt

from pydantic import BaseModel


class PlaybookOverview(BaseModel):
    name: str
    version: dt.datetime
    default_version: dt.datetime | None = None
    created_at: dt.datetime
    created_by: str | None = None
    updated_by: str | None = None


class Playbook(PlaybookOverview):
    content: bytes | None = None


class PlaybookResponse(BaseModel):
    name: str
    version: str
    default_version: str
    available_versions: list[str]
    original_content: str
    modified_content: str


class PlaybookListResponse(BaseModel):
    playbooks: list[str]


class PlaybookVersionResponse(BaseModel):
    playbook_version: str
    original_content: str
    modified_content: str
    available_versions: list[str] | None = None
    default_version: str | None = None


class PlaybookSaveRequest(BaseModel):
    content: str
