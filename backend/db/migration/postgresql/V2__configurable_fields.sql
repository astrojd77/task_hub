-- Configurable dropdown fields and per-source defaults — PostgreSQL
--
-- field_configs   what options a dropdown offers, and what it is called.
-- source_defaults what an import flow pre-fills before the user reviews it.
--
-- Custom field *values* live in tasks.custom_fields rather than in columns of
-- their own, so adding a field ("Type", "Platform") needs no migration. The
-- trade-off is that the database enforces nothing about them; validation is in
-- app/services/field_config.py.
--
-- No seed rows here. Builtin field configs are materialised from the canonical
-- enums on first read, so the code enums stay the single source of the default
-- scales and this migration cannot go stale against them.

ALTER TABLE tasks ADD COLUMN custom_fields JSONB;
UPDATE tasks SET custom_fields = '{}'::jsonb WHERE custom_fields IS NULL;
ALTER TABLE tasks ALTER COLUMN custom_fields SET NOT NULL;

CREATE TABLE field_configs (
    id          VARCHAR(36)  NOT NULL,
    field_key   VARCHAR(50)  NOT NULL,
    label       VARCHAR(100) NOT NULL,
    -- 'builtin' (backed by a tasks column) or 'custom' (lives in custom_fields)
    kind        VARCHAR(16)  NOT NULL,
    -- [{"value": "bug", "label": "Bug"}, ...] — array order is display order
    options     JSONB        NOT NULL,
    enabled     BOOLEAN      NOT NULL,
    is_required BOOLEAN      NOT NULL,
    sort_order  INTEGER      NOT NULL,
    created_at  TIMESTAMP    NOT NULL,
    updated_at  TIMESTAMP    NOT NULL,
    CONSTRAINT pk_field_configs PRIMARY KEY (id),
    CONSTRAINT uq_field_configs_key UNIQUE (field_key)
);

CREATE TABLE source_defaults (
    id              VARCHAR(36)  NOT NULL,
    source_provider VARCHAR(32)  NOT NULL,
    field_key       VARCHAR(50)  NOT NULL,
    value           VARCHAR(200) NOT NULL,
    created_at      TIMESTAMP    NOT NULL,
    updated_at      TIMESTAMP    NOT NULL,
    CONSTRAINT pk_source_defaults PRIMARY KEY (id),
    -- One default per field per import flow.
    CONSTRAINT uq_source_defaults UNIQUE (source_provider, field_key)
);
