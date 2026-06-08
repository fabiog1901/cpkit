CREATE SCHEMA cpkit;
GRANT USAGE ON SCHEMA cpkit TO cp;

CREATE SEQUENCE cpkit.mq_seq MINVALUE 1 MAXVALUE 9223372036854775807 INCREMENT 1 START 1 PER NODE CACHE 100;
CREATE TABLE cpkit.mq (
    msg_id INT8 NOT NULL DEFAULT nextval('cpkit.mq_seq'::REGCLASS),
    start_after TIMESTAMPTZ NOT NULL DEFAULT now():::TIMESTAMPTZ,
    msg_type STRING NOT NULL,
    msg_data JSONB NOT NULL DEFAULT '{}':::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now():::TIMESTAMPTZ,
    created_by STRING NOT NULL DEFAULT 'system':::STRING,
    CONSTRAINT pk PRIMARY KEY (msg_id ASC)
);

INSERT INTO cpkit.mq (msg_type, start_after)
VALUES ('FAIL_ZOMBIE_JOBS', now() + INTERVAL '300s' + (random()*10)::INTERVAL);

CREATE TABLE cpkit.jobs (
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

CREATE TABLE cpkit.tasks (
    job_id INT8 NOT NULL,
    task_id INT2 NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    task_name STRING NULL,
    task_desc STRING NULL,
    CONSTRAINT pk PRIMARY KEY (job_id ASC, task_id ASC),
    CONSTRAINT job_id_in_jobs FOREIGN KEY (job_id) REFERENCES cpkit.jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE cpkit.event_log (
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

CREATE TABLE cpkit.settings (
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

CREATE TABLE cpkit.api_keys (
    access_key STRING NOT NULL,
    encrypted_secret_access_key BYTES NOT NULL,
    owner STRING NOT NULL,
    valid_until TIMESTAMPTZ NOT NULL,
    roles STRING[] NULL,
    CONSTRAINT pk_api_keys PRIMARY KEY (access_key ASC)
);

CREATE TABLE cpkit.oidc_sessions (
    session_id STRING NOT NULL,
    encrypted_id_token BYTES NOT NULL,
    encrypted_refresh_token BYTES NULL,
    token_expires_at TIMESTAMPTZ NOT NULL,
    session_expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now():::TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now():::TIMESTAMPTZ ON UPDATE now():::TIMESTAMPTZ,
    CONSTRAINT pk_oidc_sessions PRIMARY KEY (session_id ASC)
) WITH (ttl = 'on', ttl_expiration_expression = e'(session_expires_at)', ttl_job_cron = '@hourly');

CREATE TABLE cpkit.role_to_groups_mappings (
    "role" STRING NOT NULL,
    groups STRING[] NULL,
    CONSTRAINT pk_role_to_groups_mappings PRIMARY KEY ("role" ASC)
);

CREATE TABLE cpkit.playbooks (
    name STRING NOT NULL,
    version TIMESTAMPTZ(0) NOT NULL DEFAULT now():::TIMESTAMPTZ,
    content BYTES NULL,
    created_at TIMESTAMPTZ NULL DEFAULT now():::TIMESTAMPTZ,
    created_by STRING NULL,
    default_version TIMESTAMPTZ NULL,
    updated_by STRING NULL,
    CONSTRAINT pk PRIMARY KEY (name ASC, version ASC)
);
