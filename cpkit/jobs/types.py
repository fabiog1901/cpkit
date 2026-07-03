"""Generic job queue data types."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QueueMessage(BaseModel):
    """Message claimed from the framework queue."""

    msg_id: int
    start_after: datetime
    msg_type: str
    msg_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    created_by: str


class JobID(BaseModel):
    job_id: int


class IntID(BaseModel):
    id: int


class LinkedResourceRef(BaseModel):
    resource_type: str
    resource_id: str


class JobStatsResponse(BaseModel):
    total: int
    running: int
    queued: int
    failed: int


class Job(BaseModel):
    job_id: int
    job_type: str
    status: str | None = None
    playbook_version: str | None = None
    description: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    created_by: str | None = None
    updated_at: datetime


class Task(BaseModel):
    job_id: int
    task_id: int
    created_at: datetime
    task_name: str | None = None
    task_desc: str | None = None


class JobDetailsResponse(BaseModel):
    job: Job
    description_yaml: str
    tasks: list[Task]
    linked_resources: list[LinkedResourceRef]


class JobRescheduleResponse(BaseModel):
    job_id: int
