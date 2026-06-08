"""Standard cpkit capability bundle for FastAPI applications."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Security
from pydantic import BaseModel

from .admin import create_cpkit_admin_router
from .audit import (
    AuditEventsService,
    build_audit_log_record,
    configure_audit_logging,
    create_events_router,
    log_event,
)
from .auth import ApiKeysService, AuthBundle, create_auth_bundle
from .db import get_pool
from .dependencies import configure_cpkit_dependencies
from .errors import ServiceError, raise_http_from_service_error
from .jobs import JobsService, QueueMessage, create_jobs_router, create_queue_worker
from .jobs.worker import QueueHandler
from .playbooks import PlaybooksService
from .repository import get_repo
from .settings import SettingsService

AuditHook = Callable[[Any, str, str, dict[str, Any] | None], None]
AuditRecordFactory = Callable[..., Any]
PayloadParser = Callable[[Any, dict[str, Any]], Any]
QueueMessageParser = Callable[[QueueMessage], Any]
QueueHandlerResolver = Callable[[QueueMessage], QueueHandler | None]
CommandModelMap = Mapping[Any, type[BaseModel]]


@dataclass(frozen=True)
class CpkitBundle:
    """Standard cpkit routers, hooks, and auth dependencies."""

    auth: AuthBundle
    routers: tuple[APIRouter, ...]
    startup_hooks: tuple[Callable[[], Any], ...]
    background_tasks: tuple[Callable[[], Any], ...]

    @property
    def require_authenticated(self):
        return self.auth.require_authenticated

    @property
    def require_user(self):
        return self.auth.require_user

    @property
    def require_readonly(self):
        return self.auth.require_readonly

    @property
    def require_admin(self):
        return self.auth.require_admin

    @property
    def get_access_scope(self):
        return self.auth.get_access_scope

    @property
    def get_audit_actor(self):
        return self.auth.get_audit_actor


def create_cpkit_bundle(
    *,
    command_models: CommandModelMap | None = None,
    command_handlers: Mapping[Any, QueueHandler] | None = None,
    parse_job_payload: PayloadParser | None = None,
    reschedule_type_map: Mapping[Any, Any] | None = None,
    resolve_queue_handler: QueueHandlerResolver | None = None,
    parse_queue_message: QueueMessageParser | None = None,
    audit_record_factory: AuditRecordFactory = build_audit_log_record,
    audit_event_hook: AuditHook | None = None,
) -> CpkitBundle:
    """Create the standard cpkit capability bundle for an application."""
    configure_audit_logging(audit_record_factory)
    effective_audit_event_hook = audit_event_hook or log_event
    normalized_command_models = _normalize_mapping(command_models)
    effective_parse_job_payload = parse_job_payload or _command_model_parser(
        normalized_command_models
    )
    effective_parse_queue_message = parse_queue_message or _queue_message_parser(
        effective_parse_job_payload
    )
    normalized_command_handlers = _normalize_mapping(command_handlers)
    effective_reschedule_type_map = {
        _type_value(source): _type_value(target)
        for source, target in (reschedule_type_map or {}).items()
    }
    auth = create_auth_bundle(
        get_repo=get_repo,
        audit_record_factory=audit_record_factory,
    )

    def validate_auth_config() -> None:
        auth.oidc.validate_config(get_repo())

    def get_api_keys_service():
        return ApiKeysService(
            get_repo(),
            created_hook=effective_audit_event_hook,
            deleted_hook=effective_audit_event_hook,
        )

    def get_events_service():
        return AuditEventsService(get_repo())

    def get_jobs_service():
        return JobsService(
            get_repo(),
            parse_payload=effective_parse_job_payload,
            reschedule_type_resolver=lambda job_type: effective_reschedule_type_map.get(
                _type_value(job_type),
                job_type,
            ),
            rescheduled_hook=effective_audit_event_hook,
        )

    def get_playbooks_service():
        return PlaybooksService(
            get_repo(),
            version_created_hook=effective_audit_event_hook,
            version_deleted_hook=effective_audit_event_hook,
            default_set_hook=effective_audit_event_hook,
        )

    def get_settings_service():
        return SettingsService(
            get_repo(),
            setting_updated_hook=_setting_updated_hook(effective_audit_event_hook),
            setting_reset_hook=_setting_reset_hook(effective_audit_event_hook),
        )

    admin_router = create_cpkit_admin_router(
        get_api_keys_service=get_api_keys_service,
        get_settings_service=get_settings_service,
        get_playbooks_service=get_playbooks_service,
        get_audit_actor=auth.get_audit_actor,
        handle_service_error=raise_http_from_service_error,
        service_error_type=ServiceError,
        dependencies=(Security(auth.require_admin),),
    )
    events_router = create_events_router(
        get_service=get_events_service,
        get_access_scope=auth.get_access_scope,
        require_readonly=auth.require_readonly,
        handle_service_error=raise_http_from_service_error,
        service_error_type=ServiceError,
    )
    jobs_router = create_jobs_router(
        get_service=get_jobs_service,
        get_access_scope=auth.get_access_scope,
        get_audit_actor=auth.get_audit_actor,
        require_readonly=auth.require_readonly,
        require_user=auth.require_user,
        handle_service_error=raise_http_from_service_error,
        service_error_type=ServiceError,
    )
    queue_worker = create_queue_worker(
        get_pool=get_pool,
        get_repo=get_repo,
        handlers=normalized_command_handlers,
        resolve_handler=resolve_queue_handler,
        parse_message=effective_parse_queue_message,
    )

    bundle = CpkitBundle(
        auth=auth,
        routers=(
            auth.router,
            admin_router,
            events_router,
            jobs_router,
        ),
        startup_hooks=(validate_auth_config,),
        background_tasks=(queue_worker,),
    )
    configure_cpkit_dependencies(bundle)
    return bundle


def _setting_updated_hook(
    audit_event_hook: AuditHook | None,
) -> Callable[[Any, str, str, str], None] | None:
    if audit_event_hook is None:
        return None

    def log_setting_updated(
        repo: Any,
        setting_id: str,
        value: str,
        updated_by: str,
    ) -> None:
        audit_event_hook(
            repo,
            updated_by,
            "SETTING_UPDATED",
            {"ID": setting_id, "value": value},
        )

    return log_setting_updated


def _setting_reset_hook(
    audit_event_hook: AuditHook | None,
) -> Callable[[Any, str, str], None] | None:
    if audit_event_hook is None:
        return None

    def log_setting_reset(repo: Any, setting_id: str, updated_by: str) -> None:
        audit_event_hook(
            repo,
            updated_by,
            "SETTING_RESET",
            {"ID": setting_id},
        )

    return log_setting_reset


def _type_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _normalize_mapping(mapping: Mapping[Any, Any] | None) -> dict[Any, Any] | None:
    if mapping is None:
        return None
    return {_type_value(key): value for key, value in mapping.items()}


def _command_model_parser(command_models: Mapping[Any, type[BaseModel]] | None):
    if command_models is None:
        raise ValueError("command_models or parse_job_payload is required.")

    def parse(command_type: Any, payload: dict[str, Any] | None) -> BaseModel:
        model_type = command_models[_type_value(command_type)]
        return model_type.model_validate(payload or {})

    return parse


def _queue_message_parser(parse_payload: PayloadParser) -> QueueMessageParser:
    def parse(message: QueueMessage) -> Any:
        return parse_payload(message.msg_type, message.msg_data)

    return parse
