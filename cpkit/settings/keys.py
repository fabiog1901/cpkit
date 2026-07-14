"""Framework-owned settings keys."""

from enum import StrEnum


class FrameworkSettingKey(StrEnum):
    auth_api_key_signature_ttl_seconds = "auth.api_key_signature_ttl_seconds"
    logging_journald_identifier = "logging.journald_identifier"
    logging_level = "logging.level"
    oidc_cache_ttl_seconds = "oidc.cache_ttl_seconds"
    oidc_enabled = "oidc.enabled"
    oidc_issuer_url = "oidc.issuer_url"
    oidc_client_id = "oidc.client_id"
    oidc_client_secret = "oidc.client_secret"
    oidc_scopes = "oidc.scopes"
    oidc_audience = "oidc.audience"
    oidc_extra_auth_params = "oidc.extra_auth_params"
    oidc_redirect_uri = "oidc.redirect_uri"
    oidc_login_path = "oidc.login_path"
    oidc_session_max_age_seconds = "oidc.session_max_age_seconds"
    oidc_refresh_leeway_seconds = "oidc.refresh_leeway_seconds"
    oidc_cookie_secure = "oidc.cookie_secure"
    oidc_cookie_samesite = "oidc.cookie_samesite"
    oidc_cookie_domain = "oidc.cookie_domain"
    oidc_verify_audience = "oidc.verify_audience"
    oidc_ui_username_claim = "oidc.ui_username_claim"
    oidc_authz_readonly_groups = "oidc.authz_readonly_groups"
    oidc_authz_user_groups = "oidc.authz_user_groups"
    oidc_authz_admin_groups = "oidc.authz_admin_groups"
    oidc_authz_groups_claim = "oidc.authz_groups_claim"
    playbooks_ssh_credential_hook_enabled = "playbooks.ssh_credential_hook.enabled"
    playbooks_ssh_credential_hook_prepare_playbook = (
        "playbooks.ssh_credential_hook.prepare_playbook"
    )
    playbooks_ssh_credential_hook_cleanup_playbook = (
        "playbooks.ssh_credential_hook.cleanup_playbook"
    )
    playbooks_ssh_credential_hook_dir_root = "playbooks.ssh_credential_hook.dir_root"
    playbooks_ssh_credential_hook_retain_artifacts_on_failure = (
        "playbooks.ssh_credential_hook.retain_artifacts_on_failure"
    )
