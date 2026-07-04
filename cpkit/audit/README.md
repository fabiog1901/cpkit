# Audit

The audit package records and exposes framework/application events such as
logins, settings changes, API key changes, reschedules, and app-defined actions.

The important idea is that audit records are app-owned objects built through a
record factory, then written through the configured repository. cpkit provides a
default `AuditLogRecord`, but apps can provide their own factory if their audit
schema differs.

## Files

- `types.py`: Default audit models, including `AuditLogRecord`.
- `recorder.py`: The common audit recorder and hooks. This is where request ids
  and job ids are resolved before calling the record factory.
- `repository.py`: Repository mixin for reading and writing `cpkit.event_log`.
- `events_service.py`: Service used by the Events page/API to list events.
- `router.py`: Read-only API routes for audit events.
- `service.py`: Generic audit emission service for app code that wants a small
  service wrapper.

## Runtime Flow

1. A service calls `log_event()` or a hook created by `create_audit_event_hook()`.
2. `AuditRecorder` resolves contextual values, currently `request_id` and
   `job_id`, through provider functions.
3. The configured record factory receives `actor_id`, `event_type`, `metadata`,
   `request_id`, and `job_id`.
4. The resulting record is written through the repository's `log_event()` method.

Best-effort audit logging should not break the user workflow. If an audit record
cannot be built or written, cpkit logs the exception and returns `False`.

