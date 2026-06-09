CREATE SCHEMA IF NOT EXISTS cpkit;

CREATE SEQUENCE IF NOT EXISTS cpkit.mq_seq MINVALUE 1 MAXVALUE 9223372036854775807 INCREMENT 1 START 1 PER NODE CACHE 100;
CREATE TABLE IF NOT EXISTS cpkit.mq (
    msg_id INT8 NOT NULL DEFAULT nextval('cpkit.mq_seq'::REGCLASS),
    start_after TIMESTAMPTZ NOT NULL DEFAULT now():::TIMESTAMPTZ,
    msg_type STRING NOT NULL,
    msg_data JSONB NOT NULL DEFAULT '{}':::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now():::TIMESTAMPTZ,
    created_by STRING NOT NULL DEFAULT 'system':::STRING,
    CONSTRAINT pk PRIMARY KEY (msg_id ASC)
);

INSERT INTO cpkit.mq (msg_type, start_after)
SELECT 'FAIL_ZOMBIE_JOBS', now() + INTERVAL '300s' + (random()*10)::INTERVAL
WHERE NOT EXISTS (
    SELECT 1
    FROM cpkit.mq
    WHERE msg_type = 'FAIL_ZOMBIE_JOBS'
);

CREATE TABLE IF NOT EXISTS cpkit.jobs (
    job_id INT8 NOT NULL,
    job_type STRING NULL,
    status STRING NULL,
    description JSONB NULL,
    created_at TIMESTAMPTZ NULL DEFAULT now():::TIMESTAMPTZ,
    created_by STRING NULL,
    updated_at TIMESTAMPTZ NULL DEFAULT now():::TIMESTAMPTZ ON UPDATE now():::TIMESTAMPTZ,
    CONSTRAINT pk PRIMARY KEY (job_id ASC)
) WITH (
    ttl = 'on',
    ttl_expiration_expression = e'(updated_at::TIMESTAMPTZ + \'90 days\'::INTERVAL)',
    ttl_job_cron = '@daily'
);

CREATE TABLE IF NOT EXISTS cpkit.tasks (
    job_id INT8 NOT NULL,
    task_id INT2 NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    task_name STRING NULL,
    task_desc STRING NULL,
    CONSTRAINT pk PRIMARY KEY (job_id ASC, task_id ASC),
    CONSTRAINT job_id_in_jobs FOREIGN KEY (job_id) REFERENCES cpkit.jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cpkit.event_log (
    ts TIMESTAMPTZ NOT NULL DEFAULT now():::TIMESTAMPTZ,
    user_id STRING NOT NULL,
    action STRING NOT NULL,
    details JSONB NULL,
    request_id UUID NULL,
    CONSTRAINT pk PRIMARY KEY (ts ASC, user_id ASC)
) WITH (
    ttl = 'on',
    ttl_expiration_expression = e'(ts::TIMESTAMPTZ + \'90 days\')',
    ttl_job_cron = '@daily'
);

CREATE TABLE IF NOT EXISTS cpkit.settings (
    key STRING NOT NULL,
    value STRING NULL,
    default_value STRING NULL,
    value_type STRING NULL,
    category STRING NULL,
    is_secret BOOL NULL DEFAULT false,
    description STRING NULL DEFAULT '':::STRING,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now():::TIMESTAMPTZ,
    updated_by STRING NULL,
    CONSTRAINT pk_settings PRIMARY KEY (key ASC)
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
    ('logging.journald_identifier',         NULL, '',                                    'string',  'logging', false, 'Optional journald SYSLOG_IDENTIFIER. When blank, the application default is used.'),
    ('logging.level',                       NULL, 'INFO',                                'string',  'logging', false, 'Root logging level used by cpkit logging setup.'),
    ('oidc.cache_ttl_seconds',              NULL, '300',                                 'integer', 'oidc',    false, 'OIDC provider metadata and JWKS cache TTL, in seconds.'),
    ('oidc.enabled',                        NULL, 'false',                               'boolean', 'oidc',    false, 'Enable browser OIDC authentication.'),
    ('oidc.issuer_url',                     NULL, '',                                    'string',  'oidc',    false, 'OIDC issuer URL.'),
    ('oidc.client_id',                      NULL, '',                                    'string',  'oidc',    false, 'OIDC client ID.'),
    ('oidc.client_secret',                  NULL, '',                                    'string',  'oidc',    true,  'OIDC client secret.'),
    ('oidc.scopes',                         NULL, 'openid profile email offline_access', 'string',  'oidc',    false, 'Space-delimited OIDC scopes requested during login.'),
    ('oidc.audience',                       NULL, '',                                    'string',  'oidc',    false, 'Optional expected JWT audience.'),
    ('oidc.extra_auth_params',              NULL, '{}',                                  'json',    'oidc',    false, 'Additional authorization request parameters as a JSON object.'),
    ('oidc.redirect_uri',                   NULL, '',                                    'string',  'oidc',    false, 'OIDC redirect URI. Leave blank to derive it from the incoming request.'),
    ('oidc.login_path',                     NULL, '/api/auth/login',                     'string',  'oidc',    false, 'Login path used when redirecting unauthenticated browser requests.'),
    ('oidc.session_max_age_seconds',        NULL, '2592000',                             'integer', 'oidc',    false, 'Maximum OIDC session lifetime, in seconds.'),
    ('oidc.refresh_leeway_seconds',         NULL, '60',                                  'integer', 'oidc',    false, 'Seconds before token expiry when refresh should be attempted.'),
    ('oidc.cookie_secure',                  NULL, 'false',                               'boolean', 'oidc',    false, 'Whether OIDC cookies require HTTPS.'),
    ('oidc.cookie_samesite',                NULL, 'lax',                                 'string',  'oidc',    false, 'SameSite value for OIDC cookies: lax, strict, or none.'),
    ('oidc.cookie_domain',                  NULL, '',                                    'string',  'oidc',    false, 'Optional OIDC cookie domain.'),
    ('oidc.verify_audience',                NULL, 'false',                               'boolean', 'oidc',    false, 'Whether ID token audience validation is required.'),
    ('oidc.ui_username_claim',              NULL, 'preferred_username',                  'string',  'oidc',    false, 'JWT claim used as the display/audit username.'),
    ('oidc.authz_readonly_groups',          NULL, '',                                    'csv',     'oidc',    false, 'Comma-delimited IdP groups mapped to the CP_READONLY role.'),
    ('oidc.authz_user_groups',              NULL, '',                                    'csv',     'oidc',    false, 'Comma-delimited IdP groups mapped to the CP_USER role.'),
    ('oidc.authz_admin_groups',             NULL, '',                                    'csv',     'oidc',    false, 'Comma-delimited IdP groups mapped to the CP_ADMIN role.'),
    ('oidc.authz_groups_claim',             NULL, 'groups',                              'string',  'oidc',    false, 'JWT claim containing IdP group memberships.')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS cpkit.api_keys (
    access_key STRING NOT NULL,
    encrypted_secret_access_key BYTES NOT NULL,
    owner STRING NOT NULL,
    valid_until TIMESTAMPTZ NOT NULL,
    roles STRING[] NULL,
    CONSTRAINT pk_api_keys PRIMARY KEY (access_key ASC)
);

CREATE TABLE IF NOT EXISTS cpkit.oidc_sessions (
    session_id STRING NOT NULL,
    encrypted_id_token BYTES NOT NULL,
    encrypted_refresh_token BYTES NULL,
    token_expires_at TIMESTAMPTZ NOT NULL,
    session_expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now():::TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now():::TIMESTAMPTZ ON UPDATE now():::TIMESTAMPTZ,
    CONSTRAINT pk_oidc_sessions PRIMARY KEY (session_id ASC)
) WITH (ttl = 'on', ttl_expiration_expression = e'(session_expires_at)', ttl_job_cron = '@hourly');

CREATE TABLE IF NOT EXISTS cpkit.role_to_groups_mappings (
    "role" STRING NOT NULL,
    groups STRING[] NULL,
    CONSTRAINT pk_role_to_groups_mappings PRIMARY KEY ("role" ASC)
);

CREATE TABLE IF NOT EXISTS cpkit.playbooks (
    name STRING NOT NULL,
    version TIMESTAMPTZ(0) NOT NULL DEFAULT now():::TIMESTAMPTZ,
    content BYTES NULL,
    created_at TIMESTAMPTZ NULL DEFAULT now():::TIMESTAMPTZ,
    created_by STRING NULL,
    default_version TIMESTAMPTZ NULL,
    updated_by STRING NULL,
    CONSTRAINT pk PRIMARY KEY (name ASC, version ASC)
);
