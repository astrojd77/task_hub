-- Rename title -> summary, and add per-source field mapping — Oracle
--
-- See the PostgreSQL script for what these are for. Oracle specifics:
-- CLOB for JSON, TIMESTAMP not DATE, VARCHAR2(n CHAR) for character semantics.
--
-- RENAME COLUMN is supported on every Oracle version this targets and does not
-- rewrite the table.

ALTER TABLE tasks RENAME COLUMN title TO summary;

CREATE TABLE source_mappings (
    id              VARCHAR2(36 CHAR)  NOT NULL,
    source_provider VARCHAR2(32 CHAR)  NOT NULL,
    field_key       VARCHAR2(50 CHAR)  NOT NULL,
    source_expr     VARCHAR2(200 CHAR),
    value_map       CLOB               NOT NULL,
    created_at      TIMESTAMP          NOT NULL,
    updated_at      TIMESTAMP          NOT NULL,
    CONSTRAINT pk_source_mappings PRIMARY KEY (id),
    CONSTRAINT uq_source_mappings UNIQUE (source_provider, field_key)
);
