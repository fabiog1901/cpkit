"""Application models for the cpkit TODO example."""

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, field_serializer


class CommandType(StrEnum):
    EXPORT_TODOS = "EXPORT_TODOS"


class Todo(BaseModel):
    todo_id: int
    title: str
    notes: str | None = None
    completed: bool = False
    created_at: datetime
    created_by: str | None = None
    updated_at: datetime
    updated_by: str | None = None

    @field_serializer("todo_id")
    def serialize_todo_id(self, todo_id: int) -> str:
        return str(todo_id)


class TodoCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    notes: str | None = None


class TodoUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    notes: str | None = None
    completed: bool | None = None


class ExportTodosRequest(BaseModel):
    format: str = Field(default="json", pattern="^(json|csv)$")
    include_completed: bool = True
    output_dir: str = "exports"


class ExportTodosPayload(BaseModel):
    format: str = Field(default="json", pattern="^(json|csv)$")
    include_completed: bool = True
    output_dir: str = "exports"

    @property
    def output_directory(self) -> Path:
        return Path(self.output_dir)


COMMAND_MODELS = {
    CommandType.EXPORT_TODOS: ExportTodosPayload,
}
