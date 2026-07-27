-- Configurable dropdown fields and per-source defaults — Oracle
--
-- See the PostgreSQL script for what these tables are for. Oracle differences:
--
--   CLOB       for JSON, as everywhere else in this schema — native JSON is
--              21c-only and app/db/types.py serialises in Python here.
--   NUMBER(1)  for booleans — Oracle had no BOOLEAN before 23c, and this is
--              what SQLAlchemy's Boolean maps to.
--   TIMESTAMP  not DATE, which has second precision only.
--
-- Flyway sends each statement separately, so no trailing slash is needed.

ALTER TABLE tasks ADD custom_fields CLOB;
UPDATE tasks SET custom_fields = '{}' WHERE custom_fields IS NULL;
ALTER TABLE tasks MODIFY custom_fields NOT NULL;

CREATE TABLE field_configs (
    id          VARCHAR2(36 CHAR)  NOT NULL,
    field_key   VARCHAR2(50 CHAR)  NOT NULL,
    label       VARCHAR2(100 CHAR) NOT NULL,
    kind        VARCHAR2(16 CHAR)  NOT NULL,
    options     CLOB               NOT NULL,
    enabled     NUMBER(1)          NOT NULL,
    is_required NUMBER(1)          NOT NULL,
    sort_order  NUMBER(10)         NOT NULL,
    created_at  TIMESTAMP          NOT NULL,
    updated_at  TIMESTAMP          NOT NULL,
    CONSTRAINT pk_field_configs PRIMARY KEY (id),
    CONSTRAINT uq_field_configs_key UNIQUE (field_key)
);

CREATE TABLE source_defaults (
    id              VARCHAR2(36 CHAR)  NOT NULL,
    source_provider VARCHAR2(32 CHAR)  NOT NULL,
    field_key       VARCHAR2(50 CHAR)  NOT NULL,
    value           VARCHAR2(200 CHAR) NOT NULL,
    created_at      TIMESTAMP          NOT NULL,
    updated_at      TIMESTAMP          NOT NULL,
    CONSTRAINT pk_source_defaults PRIMARY KEY (id),
    CONSTRAINT uq_source_defaults UNIQUE (source_provider, field_key)
);
