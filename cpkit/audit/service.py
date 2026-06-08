"""Generic audit emission service."""

from enum import StrEnum
from typing import Any

from .types import AuditOutcome, AuditRecordCreate


class AuditService:
    def __init__(self, repo):
        self.repo = repo

    async def emit(
        self,
        event_type: str | StrEnum,
        *,
        actor_id: str | None = None,
        actor_name: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        outcome: AuditOutcome = AuditOutcome.REQUESTED,
        metadata: dict[str, Any] | None = None,
    ):
        record = AuditRecordCreate(
            event_type=str(event_type),
            actor_id=actor_id,
            actor_name=actor_name,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            metadata=metadata or {},
        )

        return await self.repo.insert(record)
