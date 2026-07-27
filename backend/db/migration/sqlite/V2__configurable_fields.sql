-- Configurable dropdown fields and per-source defaults — SQLite (dev only)
--
-- See the PostgreSQL script for what these tables are for.
--
-- SQLite cannot add a NOT NULL column without a default, and cannot ALTER a
-- column afterwards, so custom_fields is declared NOT NULL DEFAULT '{}' in one
-- statement. The other dialects add-then-tighten instead, which is why this
-- file differs from theirs here rather than anywhere structural.

ALTER TABLE tasks ADD COLUMN custom_fields JSON NOT NULL DEFAULT '{}';

CREATE TABLE field_configs (
    id          VARCHAR(36)  NOT NULL,
    field_key   VARCHAR(50)  NOT NULL,
    label       VARCHAR(100) NOT NULL,
    kind        VARCHAR(16)  NOT NULL,
    options     JSON         NOT NULL,
    enabled     BOOLEAN      NOT NULL,
    is_required BOOLEAN      NOT NULL,
    sort_order  INTEGER      NOT NULL,
    created_at  DATETIME     NOT NULL,
    updated_at  DATETIME     NOT NULL,
    CONSTRAINT pk_field_configs PRIMARY KEY (id),
    CONSTRAINT uq_field_configs_key UNIQUE (field_key)
);

CREATE TABLE source_defaults (
    id              VARCHAR(36)  NOT NULL,
    source_provider VARCHAR(32)  NOT NULL,
    field_key       VARCHAR(50)  NOT NULL,
    value           VARCHAR(200) NOT NULL,
    created_at      DATETIME     NOT NULL,
    updated_at      DATETIME     NOT NULL,
    CONSTRAINT pk_source_defaults PRIMARY KEY (id),
    CONSTRAINT uq_source_defaults UNIQUE (source_provider, field_key)
);
