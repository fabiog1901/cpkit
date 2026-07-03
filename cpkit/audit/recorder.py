"""Audit recording helpers for application-owned audit record models."""

import logging
from collections.abc import Callable
from contextvars import ContextVar
from enum import StrEnum
from typing import Any, Protocol

from cpkit.logging import request_id_ctx

from .types import AuditLogRecord

logger = logging.getLogger(__name__)
_audit_record_factory: Callable[..., Any] | None = None
job_id_ctx: ContextVar[int | None] = ContextVar("job_id", default=None)


class AuditRecordWriter(Protocol):
    """Repository-like object that can persist an application audit record."""

    def log_event(self, record: Any) -> Any: ...


def write_audit_record(
    writer: Any,
    record: Any,
    *,
    method_name: str = "log_event",
) -> Any:
    """Write an application-owned audit record through a repository-like writer."""
    return getattr(writer, method_name)(record)


def write_audit_record_best_effort(
    writer: Any,
    record: Any,
    *,
    event_type: str | None = None,
    method_name: str = "log_event",
    event_logger: logging.Logger | None = None,
) -> bool:
    """Write an audit record without letting audit failures fail the caller."""
    active_logger = event_logger or logger

    try:
        write_audit_record(writer, record, method_name=method_name)
    except Exception:
        active_logger.exception("Failed to write audit event %s", event_type or record)
        return False

    return True


class AuditRecorder:
    """Build and persist application-owned audit records with common mechanics."""

    def __init__(
        self,
        writer: AuditRecordWriter,
        record_factory: Callable[..., Any],
        *,
        request_id_provider: Callable[[], str | None] | None = None,
        job_id_provider: Callable[[], int | None] | None = None,
        method_name: str = "log_event",
        event_logger: logging.Logger | None = None,
    ) -> None:
        self.writer = writer
        self.record_factory = record_factory
        self.request_id_provider = request_id_provider
        self.job_id_provider = job_id_provider
        self.method_name = method_name
        self.logger = event_logger or logger

    def emit(
        self,
        event_type: str | StrEnum,
        *,
        actor_id: str,
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
        job_id: int | None = None,
    ) -> Any:
        """Create and write an application-owned audit record."""
        record = self._build_record(
            event_type,
            actor_id=actor_id,
            metadata=metadata,
            request_id=request_id,
            job_id=job_id,
        )
        return write_audit_record(
            self.writer,
            record,
            method_name=self.method_name,
        )

    def emit_best_effort(
        self,
        event_type: str | StrEnum,
        *,
        actor_id: str,
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
        job_id: int | None = None,
    ) -> bool:
        """Create and write an audit record without failing the caller."""
        record = self._build_record(
            event_type,
            actor_id=actor_id,
            metadata=metadata,
            request_id=request_id,
            job_id=job_id,
        )
        return write_audit_record_best_effort(
            self.writer,
            record,
            event_type=str(event_type),
            method_name=self.method_name,
            event_logger=self.logger,
        )

    def _build_record(
        self,
        event_type: str | StrEnum,
        *,
        actor_id: str,
        metadata: dict[str, Any] | None,
        request_id: str | None,
        job_id: int | None,
    ) -> Any:
        effective_request_id = request_id
        if effective_request_id is None and self.request_id_provider is not None:
            effective_request_id = self.request_id_provider()

        effective_job_id = job_id
        if effective_job_id is None and self.job_id_provider is not None:
            effective_job_id = self.job_id_provider()

        return self.record_factory(
            actor_id=actor_id,
            event_type=str(event_type),
            metadata=metadata,
            request_id=effective_request_id,
            job_id=effective_job_id,
        )


def build_audit_log_record(
    *,
    actor_id: str,
    event_type: str,
    metadata: dict[str, Any] | None,
    request_id: str | None,
    job_id: int | None,
    default_metadata: dict[str, Any] | None = None,
) -> AuditLogRecord:
    """Build the standard cpkit audit log record."""
    effective_metadata = metadata if metadata is not None else default_metadata
    return AuditLogRecord(
        user_id=actor_id,
        action=event_type,
        job_id=job_id,
        details=effective_metadata,
        request_id=request_id,
    )


def configure_audit_logging(record_factory: Callable[..., Any]) -> None:
    """Configure the default audit record factory for framework logging APIs."""
    global _audit_record_factory
    _audit_record_factory = record_factory


def create_audit_event_hook(
    record_factory: Callable[..., Any],
    *,
    request_id_provider: Callable[[], str | None] = request_id_ctx.get,
    job_id_provider: Callable[[], int | None] = job_id_ctx.get,
    best_effort: bool = True,
    event_logger: logging.Logger | None = None,
) -> Callable[[Any, str, str | StrEnum, dict[str, Any] | None], None]:
    """Create a reusable audit hook backed by an application record factory."""

    def emit_audit_event(
        repo: Any,
        actor_id: str,
        action: str | StrEnum,
        details: dict[str, Any] | None = None,
    ) -> None:
        recorder = AuditRecorder(
            repo,
            record_factory,
            request_id_provider=request_id_provider,
            job_id_provider=job_id_provider,
            event_logger=event_logger,
        )
        if best_effort:
            recorder.emit_best_effort(
                action,
                actor_id=actor_id,
                metadata=details,
            )
            return

        recorder.emit(
            action,
            actor_id=actor_id,
            metadata=details,
        )

    return emit_audit_event


def log_event(
    repo: Any,
    actor_id: str,
    action: str | StrEnum,
    details: dict[str, Any] | None = None,
) -> None:
    """Best-effort audit logging for cpkit-backed service actions."""
    if _audit_record_factory is None:
        raise RuntimeError("cpkit audit logging has not been configured.")

    create_audit_event_hook(
        _audit_record_factory,
        event_logger=logger,
    )(
        repo,
        actor_id,
        action,
        details,
    )
