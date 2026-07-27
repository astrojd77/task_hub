-- Rename title -> summary, and add per-source field mapping — SQLite (dev only)
--
-- See the PostgreSQL script for what these are for.
-- RENAME COLUMN needs SQLite 3.25+ (2018), which every supported Python ships.

ALTER TABLE tasks RENAME COLUMN title TO summary;

CREATE TABLE source_mappings (
    id              VARCHAR(36) NOT NULL,
    source_provider VARCHAR(32) NOT NULL,
    field_key       VARCHAR(50) NOT NULL,
    source_expr     VARCHAR(200),
    value_map       JSON        NOT NULL,
    created_at      DATETIME    NOT NULL,
    updated_at      DATETIME    NOT NULL,
    CONSTRAINT pk_source_mappings PRIMARY KEY (id),
    CONSTRAINT uq_source_mappings UNIQUE (source_provider, field_key)
);
