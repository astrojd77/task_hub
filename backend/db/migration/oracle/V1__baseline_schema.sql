-- Task Hub baseline schema — Oracle
--
-- The production dialect. Differences from the PostgreSQL script, and why:
--
--   VARCHAR2(n CHAR)  explicit CHAR semantics, so a length is characters
--                     rather than bytes under AL32UTF8.
--   CLOB              Oracle only gained a native JSON type in 21c; CLOB works
--                     on every supported version and python-oracledb thin mode
--                     handles it without a client install. app/db/types.py
--                     serialises/deserialises in Python for this dialect.
--   TIMESTAMP         *not* DATE — Oracle's DATE has second precision only,
--                     which makes a bulk import's rows tie on created_at and
--                     sort unstably.
--
-- No CHECK constraints on the enum columns: the canonical scales are meant to
-- be tunable, and validation is server-authoritative in the Pydantic layer.
--
-- Every identifier here is <= 30 characters, so it survives Oracle's
-- identifier cap unquoted.

CREATE TABLE tasks (
    id              VARCHAR2(36 CHAR)  NOT NULL,
    title           VARCHAR2(500 CHAR) NOT NULL,
    description     CLOB,
    status          VARCHAR2(20 CHAR)  NOT NULL,
    priority        VARCHAR2(20 CHAR)  NOT NULL,
    criticality     VARCHAR2(20 CHAR),
    impact_size     VARCHAR2(20 CHAR),
    due_date        DATE,
    assignee        VARCHAR2(200 CHAR),
    project         VARCHAR2(200 CHAR),
    labels          CLOB               NOT NULL,
    source_provider VARCHAR2(32 CHAR)  NOT NULL,
    -- 32 + 255 chars stays well inside Oracle's index-key byte limit for the
    -- composite unique constraint below, even at 4 bytes per character.
    source_ref      VARCHAR2(255 CHAR) NOT NULL,
    external_refs   CLOB               NOT NULL,
    raw_payload     CLOB,
    destination     VARCHAR2(32 CHAR),
    created_at      TIMESTAMP          NOT NULL,
    updated_at      TIMESTAMP          NOT NULL,
    CONSTRAINT pk_tasks PRIMARY KEY (id),
    CONSTRAINT uq_tasks_source UNIQUE (source_provider, source_ref)
);

CREATE INDEX ix_tasks_due_date ON tasks (due_date);
CREATE INDEX ix_tasks_status   ON tasks (status);
CREATE INDEX ix_tasks_project  ON tasks (project);

CREATE TABLE project_routes (
    id          VARCHAR2(36 CHAR)  NOT NULL,
    project     VARCHAR2(200 CHAR) NOT NULL,
    destination VARCHAR2(32 CHAR)  NOT NULL,
    created_at  TIMESTAMP          NOT NULL,
    updated_at  TIMESTAMP          NOT NULL,
    CONSTRAINT pk_project_routes PRIMARY KEY (id),
    CONSTRAINT uq_project_routes_project UNIQUE (project)
);
