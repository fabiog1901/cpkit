CREATE SCHEMA IF NOT EXISTS cpkit;

CREATE SEQUENCE IF NOT EXISTS cpkit.mq_seq MINVALUE 1 MAXVALUE 9223372036854775807 INCREMENT 1 START 1;

CREATE TABLE IF NOT EXISTS cpkit.mq (
    msg_id INT8 NOT NULL DEFAULT nextval('cpkit.mq_seq'::REGCLASS),
    start_after TIMESTAMPTZ NOT NULL DEFAULT now(),
    msg_type TEXT NOT NULL,
    msg_data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL DEFAULT 'system',
    is_recurring BOOLEAN NOT NULL DEFAULT false,
    CONSTRAINT pk_mq PRIMARY KEY (msg_id)
);


CREATE UNIQUE INDEX IF NOT EXISTS uq_mq_recurring_msg_type
ON cpkit.mq (msg_type)
WHERE is_recurring = true;

INSERT INTO cpkit.mq (msg_type, msg_data, created_by, start_after, is_recurring)
SELECT 'FAIL_ZOMBIE_JOBS', '{}', 'system', now() + INTERVAL '300s' + (random() * INTERVAL '10s'), true
WHERE NOT EXISTS (
    SELECT 1
    FROM cpkit.mq
    WHERE msg_type = 'FAIL_ZOMBIE_JOBS'
        AND is_recurring = true
);

CREATE TABLE IF NOT EXISTS cpkit.jobs (
    job_id INT8 NOT NULL,
    job_type TEXT NULL,
    status TEXT NULL,
    playbook_version TEXT NULL,
    description JSONB NULL,
    created_at TIMESTAMPTZ NULL DEFAULT now(),
    created_by TEXT NULL,
    updated_at TIMESTAMPTZ NULL DEFAULT now(),
    CONSTRAINT pk_jobs PRIMARY KEY (job_id)
);

CREATE TABLE IF NOT EXISTS cpkit.tasks (
    job_id INT8 NOT NULL,
    task_id INT2 NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    task_name TEXT NULL,
    task_desc TEXT NULL,
    CONSTRAINT pk_tasks PRIMARY KEY (job_id, task_id),
    CONSTRAINT job_id_in_jobs FOREIGN KEY (job_id) REFERENCES cpkit.jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cpkit.event_log (
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    job_id INT8 NULL,
    details JSONB NULL,
    request_id UUID NULL,
    CONSTRAINT pk_event_log PRIMARY KEY (ts, user_id )
);

CREATE TABLE IF NOT EXISTS cpkit.settings (
    key TEXT NOT NULL,
    value TEXT NULL,
    default_value TEXT NULL,
    value_type TEXT NULL,
    category TEXT NULL,
    is_secret BOOL NULL DEFAULT false,
    description TEXT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT NULL,
    CONSTRAINT pk_settings PRIMARY KEY (key)
);

INSERT INTO cpkit.settings (
    key,
    value,
    default_value,
    value_type,
    category,
    is_secret,
    description
)
VALUES
    ('auth.api_key_signature_ttl_seconds',  NULL, '300',                                 'integer', 'auth',    false, 'Maximum accepted age, in seconds, for signed API key requests.'),
    ('logging.journald_identifier',         NULL, '',                                    'TEXT',  'logging', false, 'Optional journald SYSLOG_IDENTIFIER. When blank, the application default is used.'),
    ('logging.level',                       NULL, 'INFO',                                'TEXT',  'logging', false, 'Root logging level used by cpkit logging setup.'),
    ('oidc.cache_ttl_seconds',              NULL, '300',                                 'integer', 'oidc',    false, 'OIDC provider metadata and JWKS cache TTL, in seconds.'),
    ('oidc.enabled',                        NULL, 'false',                               'boolean', 'oidc',    false, 'Enable browser OIDC authentication.'),
    ('oidc.issuer_url',                     NULL, '',                                    'TEXT',  'oidc',    false, 'OIDC issuer URL.'),
    ('oidc.client_id',                      NULL, '',                                    'TEXT',  'oidc',    false, 'OIDC client ID.'),
    ('oidc.client_secret',                  NULL, '',                                    'TEXT',  'oidc',    true,  'OIDC client secret.'),
    ('oidc.scopes',                         NULL, 'openid profile email offline_access', 'TEXT',  'oidc',    false, 'Space-delimited OIDC scopes requested during login.'),
    ('oidc.audience',                       NULL, '',                                    'TEXT',  'oidc',    false, 'Optional expected JWT audience.'),
    ('oidc.extra_auth_params',              NULL, '{}',                                  'json',    'oidc',    false, 'Additional authorization request parameters as a JSON object.'),
    ('oidc.redirect_uri',                   NULL, '',                                    'TEXT',  'oidc',    false, 'OIDC redirect URI. Leave blank to derive it from the incoming request.'),
    ('oidc.login_path',                     NULL, '/api/auth/login',                     'TEXT',  'oidc',    false, 'Login path used when redirecting unauthenticated browser requests.'),
    ('oidc.session_max_age_seconds',        NULL, '2592000',                             'integer', 'oidc',    false, 'Maximum OIDC session lifetime, in seconds.'),
    ('oidc.refresh_leeway_seconds',         NULL, '60',                                  'integer', 'oidc',    false, 'Seconds before token expiry when refresh should be attempted.'),
    ('oidc.cookie_secure',                  NULL, 'false',                               'boolean', 'oidc',    false, 'Whether OIDC cookies require HTTPS.'),
    ('oidc.cookie_samesite',                NULL, 'lax',                                 'TEXT',  'oidc',    false, 'SameSite value for OIDC cookies: lax, strict, or none.'),
    ('oidc.cookie_domain',                  NULL, '',                                    'TEXT',  'oidc',    false, 'Optional OIDC cookie domain.'),
    ('oidc.verify_audience',                NULL, 'false',                               'boolean', 'oidc',    false, 'Whether ID token audience validation is required.'),
    ('oidc.ui_username_claim',              NULL, 'preferred_username',                  'TEXT',  'oidc',    false, 'JWT claim used as the display/audit username.'),
    ('oidc.authz_readonly_groups',          NULL, '',                                    'csv',     'oidc',    false, 'Comma-delimited IdP groups mapped to the CP_READONLY role.'),
    ('oidc.authz_user_groups',              NULL, '',                                    'csv',     'oidc',    false, 'Comma-delimited IdP groups mapped to the CP_USER role.'),
    ('oidc.authz_admin_groups',             NULL, '',                                    'csv',     'oidc',    false, 'Comma-delimited IdP groups mapped to the CP_ADMIN role.'),
    ('oidc.authz_groups_claim',             NULL, 'groups',                              'TEXT',  'oidc',    false, 'JWT claim containing IdP group memberships.'),
    ('playbooks.ssh_credential_hook.enabled', NULL, 'false',                             'boolean', 'playbooks', false, 'Enable SSH credential preparation and cleanup hooks before running playbooks.'),
    ('playbooks.ssh_credential_hook.prepare_playbook', NULL, 'SSH_CREDENTIAL_PREPARE',   'TEXT',    'playbooks', false, 'Playbook name used to prepare temporary SSH credentials.'),
    ('playbooks.ssh_credential_hook.cleanup_playbook', NULL, 'SSH_CREDENTIAL_CLEANUP',   'TEXT',    'playbooks', false, 'Playbook name used to clean up temporary SSH credentials.'),
    ('playbooks.ssh_credential_hook.dir_root', NULL, '/tmp/cpkit/jobs',                  'TEXT',    'playbooks', false, 'Directory root used for job-scoped temporary SSH credential material.'),
    ('playbooks.ssh_credential_hook.retain_artifacts_on_failure', NULL, 'false',         'boolean', 'playbooks', false, 'Retain job-scoped SSH credential artifacts when playbook execution fails.')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS cpkit.api_keys (
    access_key TEXT NOT NULL,
    encrypted_secret_access_key BYTEA NOT NULL,
    owner TEXT NOT NULL,
    valid_until TIMESTAMPTZ NOT NULL,
    roles TEXT[] NULL,
    CONSTRAINT pk_api_keys PRIMARY KEY (access_key)
);

CREATE TABLE IF NOT EXISTS cpkit.oidc_sessions (
    session_id TEXT NOT NULL,
    encrypted_id_token BYTEA NOT NULL,
    encrypted_refresh_token BYTEA NULL,
    token_expires_at TIMESTAMPTZ NOT NULL,
    session_expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_oidc_sessions PRIMARY KEY (session_id)
);

CREATE TABLE IF NOT EXISTS cpkit.role_to_groups_mappings (
    "role" TEXT NOT NULL,
    groups TEXT[] NULL,
    CONSTRAINT pk_role_to_groups_mappings PRIMARY KEY ("role")
);

CREATE TABLE IF NOT EXISTS cpkit.playbooks (
    name TEXT NOT NULL,
    version TIMESTAMPTZ(0) NOT NULL DEFAULT now(),
    content BYTEA NULL,
    created_at TIMESTAMPTZ NULL DEFAULT now(),
    created_by TEXT NULL,
    default_version TIMESTAMPTZ NULL,
    updated_by TEXT NULL,
    CONSTRAINT pk_playbooks PRIMARY KEY (name, version)
);
