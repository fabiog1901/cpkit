# Code Map

<!-- GENERATED FILE: DO NOT EDIT -->

This file is a deterministic map of the Python package surface in this repository.
Regenerate it after structural code changes with:

```bash
python tools/codemap.py --write
```

## Project

- Name: `cpkit`
- Package roots: `cpkit`

## Entry Points

- none found

## Packages

| Package | Modules | Classes | Functions | Routes |
| --- | ---: | ---: | ---: | ---: |
| `cpkit` | 65 | 80 | 63 | 0 |

## API Routes

- none found

## Command Handlers

- none found

## Modules

| File | Public Surface |
| --- | --- |
| `cpkit/__init__.py` | Reusable control-plane framework primitives. |
| `cpkit/admin.py` | Admin router assembly for framework-owned capabilities.; functions: create_cpkit_admin_router |
| `cpkit/app.py` | FastAPI application bootstrap helpers.; functions: create_cpkit_app |
| `cpkit/audit/__init__.py` | Generic audit record types and service helpers. |
| `cpkit/audit/events_service.py` | Service helpers for framework audit event reads.; classes: AuditEventsService |
| `cpkit/audit/recorder.py` | Audit recording helpers for application-owned audit record models.; classes: AuditRecordWriter, AuditRecorder; functions: write_audit_record, write_audit_record_best_effort, build_audit_log_record, configure_audit_logging, create_audit_event_hook, log_event |
| `cpkit/audit/repository.py` | Repository helpers for framework-owned audit tables.; classes: AuditEventsRepositoryMixin |
| `cpkit/audit/router.py` | Audit event HTTP routes for cpkit FastAPI apps.; functions: create_events_router |
| `cpkit/audit/service.py` | Generic audit emission service.; classes: AuditService |
| `cpkit/audit/types.py` | Generic audit data types.; classes: AuditOutcome, AuditRecordCreate, AuditLogRecord, AuditEventCountResponse |
| `cpkit/auth/__init__.py` | Reusable authentication helpers. |
| `cpkit/auth/api_key_router.py` | FastAPI routes for framework API-key management.; functions: create_api_keys_router |
| `cpkit/auth/api_key_service.py` | Service helpers for framework API-key management.; classes: ApiKeysService |
| `cpkit/auth/api_keys.py` | Reusable API-key request signing helpers.; classes: APIKeyAuthenticationError, APIKeyRepository, APIKeyAuthenticator; functions: parse_api_key_timestamp, request_target_bytes, build_api_key_signature_payload, api_key_signature |
| `cpkit/auth/bundle.py` | Bundled authentication wiring for cpkit FastAPI apps.; classes: AuthBundle; functions: create_auth_bundle |
| `cpkit/auth/claims.py` | Claim normalization helpers.; functions: claim_groups, claims_groups, jsonable_role_groups |
| `cpkit/auth/config.py` | OIDC configuration derived from framework settings.; classes: OIDCConfig |
| `cpkit/auth/dependencies.py` | FastAPI authentication dependency helpers for cpkit apps.; classes: AuthDependencies; functions: create_auth_dependencies |
| `cpkit/auth/oidc.py` | Reusable OIDC provider client mechanics.; classes: OIDCAuthenticationError, OIDCSessionRepository, OIDCProviderClient, OIDCSessionManager, OIDCManager |
| `cpkit/auth/redirects.py` | Redirect target validation helpers.; functions: safe_next_path |
| `cpkit/auth/repositories.py` | Repository mixins for framework-owned auth tables.; classes: APIKeysRepositoryMixin, OIDCSessionsRepositoryMixin, RoleGroupMappingsRepositoryMixin |
| `cpkit/auth/router.py` | OIDC HTTP routes for cpkit FastAPI apps.; functions: create_oidc_router |
| `cpkit/auth/secrets.py` | Versioned symmetric secret encryption helpers.; functions: validate_secret_crypto_config, encrypt_secret, decrypt_secret |
| `cpkit/auth/types.py` | Generic auth capability data types.; classes: ApiKeyRecord, ApiKeySummary, ApiKeyCreateRequest, ApiKeyCreateRequestInDB, ApiKeyCreateResponse, OIDCSessionRecord, RoleGroupMap |
| `cpkit/bundle.py` | Standard cpkit capability bundle for FastAPI applications.; classes: CpkitBundle; functions: create_cpkit_bundle |
| `cpkit/cli/__init__.py` | Reusable command-line helpers for cpkit applications. |
| `cpkit/cli/__main__.py` | Module entry point for cpkit CLI helpers. |
| `cpkit/cli/base.py` | Base application CLI for cpkit apps.; classes: ApplicationCLI; functions: main |
| `cpkit/cli/migration.py` | Database migration and preflight helpers for cpkit applications.; functions: apply_sql_file, check_database, check_table |
| `cpkit/cli/server.py` | ASGI server helpers for cpkit application CLIs.; functions: serve_uvicorn |
| `cpkit/config/__init__.py` | Configuration helpers. |
| `cpkit/config/env.py` | Helpers for parsing environment-style configuration values.; functions: as_bool, safe_csv_set, safe_json_string_dict |
| `cpkit/db/__init__.py` | Database infrastructure helpers. |
| `cpkit/db/postgres.py` | Low-level Postgres metadata database infrastructure.; classes: Dict2JsonbDumper, SelectorDumper; functions: execute_stmt, fetch_all, fetch_one, fetch_scalar, initialize_postgres, get_pool, close_db, translate_database_error |
| `cpkit/dependencies.py` | Application-scoped dependency callables exposed by cpkit.; functions: configure_cpkit_dependencies, require_authenticated, require_user, require_readonly, require_admin, get_access_scope, get_audit_actor |
| `cpkit/errors/__init__.py` | Shared framework exception types. |
| `cpkit/errors/http.py` | FastAPI translation helpers for framework service errors.; functions: raise_http_from_service_error |
| `cpkit/errors/repository.py` | Repository-layer exception types.; classes: RepositoryError, RepositoryUnavailableError, RepositoryConflictError, RepositoryValidationError, RepositoryPermissionError |
| `cpkit/errors/service.py` | Service-layer exception types and repository error translation.; classes: ServiceError, ServiceUnavailableError, ServiceConflictError, ServiceValidationError, ServiceAuthorizationError, ServiceNotFoundError; functions: from_repository_error |
| `cpkit/jobs/__init__.py` | Framework-owned job queue primitives. |
| `cpkit/jobs/maintenance.py` | Framework job maintenance handlers.; functions: create_fail_zombie_jobs_handler |
| `cpkit/jobs/repository.py` | Repository helpers for the framework message queue.; classes: QueueRepositoryMixin, QueueJobRepositoryMixin, JobsRepositoryMixin |
| `cpkit/jobs/router.py` | FastAPI routes for framework job management.; functions: create_jobs_router |
| `cpkit/jobs/service.py` | Service helpers for framework job history and rescheduling.; classes: JobsService |
| `cpkit/jobs/types.py` | Generic job queue data types.; classes: QueueMessage, JobID, IntID, LinkedResourceRef, JobStatsResponse, Job, Task, JobDetailsResponse, JobRescheduleResponse |
| `cpkit/jobs/worker.py` | Generic queue worker loop.; functions: create_queue_worker, run_queue_worker |
| `cpkit/logging/__init__.py` | Logging setup and request context helpers. |
| `cpkit/logging/context.py` | Request-aware logging context.; classes: RequestIDFilter, ShorthandFormatter |
| `cpkit/logging/middleware.py` | FastAPI request logging middleware helpers.; functions: request_logging_middleware |
| `cpkit/logging/setup.py` | Logging configuration for operational messages.; functions: configure_logging |
| `cpkit/playbooks/__init__.py` | Versioned playbook models and repository helpers. |
| `cpkit/playbooks/ansible.py` | Ansible runner helpers for framework-managed playbooks.; classes: RunnerResult, LiteRunnerResult, AnsibleRunner, LiteAnsibleRunner; functions: run_playbook, run_playbook_lite |
| `cpkit/playbooks/repository.py` | Repository mixin for framework-owned versioned playbooks.; classes: PlaybooksRepositoryMixin |
| `cpkit/playbooks/router.py` | FastAPI routes for framework playbook management.; functions: create_playbooks_router |
| `cpkit/playbooks/service.py` | Service helpers for versioned playbook management.; classes: PlaybooksService |
| `cpkit/playbooks/types.py` | Generic playbook data types.; classes: PlaybookOverview, Playbook, PlaybookResponse, PlaybookVersionResponse, PlaybookSaveRequest |
| `cpkit/repository.py` | Repository factory helpers for cpkit applications.; classes: CPKitRepo; functions: configure_repository, get_repo |
| `cpkit/settings/__init__.py` | Settings models and repository helpers. |
| `cpkit/settings/keys.py` | Framework-owned settings keys.; classes: FrameworkSettingKey |
| `cpkit/settings/repository.py` | Repository mixin for a key/value settings table.; classes: SettingsRepositoryMixin |
| `cpkit/settings/router.py` | FastAPI routes for framework settings management.; functions: create_settings_router |
| `cpkit/settings/service.py` | Service helpers for settings management.; classes: SettingsServiceMixin, SettingsService |
| `cpkit/settings/types.py` | Generic settings data types.; classes: SettingNotFoundError, SettingRecord, SettingUpdateRequest |
| `cpkit/time.py` | Framework timestamp display and parsing constants. |
| `cpkit/webapp/__init__.py` | Packaged cpkit template webapp assets.; functions: template_webapp_directory |
