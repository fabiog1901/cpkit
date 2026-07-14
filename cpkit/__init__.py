"""Reusable control-plane framework primitives."""

from .admin import create_cpkit_admin_router
from .app import create_cpkit_app
from .bundle import CpkitBundle, create_cpkit_bundle
from .cli import ApplicationCLI
from .dependencies import (
    configure_cpkit_dependencies,
    get_access_scope,
    get_audit_actor,
    require_admin,
    require_authenticated,
    require_readonly,
    require_user,
)
from .playbooks import PlaybookRunOptions, configure_playbook_run_options
from .repository import CPKitRepo, configure_repository, get_repo
from .resources import cpkit_ddl_path, cpkit_resources_directory
from .time import STRFTIME, TS_FORMAT
from .webapp import template_webapp_directory

__all__ = [
    "CPKitRepo",
    "ApplicationCLI",
    "CpkitBundle",
    "PlaybookRunOptions",
    "STRFTIME",
    "TS_FORMAT",
    "configure_cpkit_dependencies",
    "configure_playbook_run_options",
    "configure_repository",
    "create_cpkit_bundle",
    "create_cpkit_admin_router",
    "create_cpkit_app",
    "cpkit_ddl_path",
    "cpkit_resources_directory",
    "get_access_scope",
    "get_audit_actor",
    "get_repo",
    "require_admin",
    "require_authenticated",
    "require_readonly",
    "require_user",
    "template_webapp_directory",
]
