CREATE TABLE IF NOT EXISTS todos (
    todo_id INT8 NOT NULL DEFAULT unique_rowid(),
    title STRING NOT NULL,
    notes STRING NULL,
    completed BOOL NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by STRING NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now() ON UPDATE now(),
    updated_by STRING NULL,
    CONSTRAINT pk_todos PRIMARY KEY (todo_id ASC)
);
