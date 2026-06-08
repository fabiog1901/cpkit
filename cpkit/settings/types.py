"""Generic settings data types."""

import datetime as dt

from pydantic import BaseModel


class SettingNotFoundError(Exception):
    pass


class SettingRecord(BaseModel):
    key: str
    value: str | None = None
    default_value: str
    value_type: str
    category: str
    is_secret: bool = False
    description: str = ""
    updated_at: dt.datetime
    updated_by: str | None = None


class SettingUpdateRequest(BaseModel):
    value: str
