"""Generic audit record types and service helpers."""

from .events_service import AuditEventsService
from .recorder import (
    AuditRecorder,
    AuditRecordWriter,
    build_audit_log_record,
    configure_audit_logging,
    create_audit_event_hook,
    log_event,
    write_audit_record,
    write_audit_record_best_effort,
)
from .repository import EVENT_LOG_TABLE, AuditEventsRepositoryMixin
from .router import create_events_router
from .service import AuditService
from .types import (
    AuditEventCountResponse,
    AuditLogRecord,
    AuditOutcome,
    AuditRecordCreate,
)

__all__ = [
    "AuditEventCountResponse",
    "AuditEventsRepositoryMixin",
    "AuditEventsService",
    "AuditLogRecord",
    "AuditOutcome",
    "AuditRecorder",
    "AuditRecordCreate",
    "AuditRecordWriter",
    "AuditService",
    "EVENT_LOG_TABLE",
    "build_audit_log_record",
    "configure_audit_logging",
    "create_events_router",
    "create_audit_event_hook",
    "log_event",
    "write_audit_record",
    "write_audit_record_best_effort",
]
