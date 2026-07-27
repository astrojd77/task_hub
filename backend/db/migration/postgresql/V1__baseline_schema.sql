-- Task Hub baseline schema — PostgreSQL
--
-- Kept deliberately in step with app/models/*.py. There is no autogenerate any
-- more, so tests/test_schema_parity.py compares this schema against the
-- SQLAlchemy metadata and fails CI if they drift.
--
-- Conventions shared with the Oracle script:
--   * id columns are VARCHAR(36) holding a Python-generated uuid4 — never a
--     DB-side default, so the same code works on every dialect.
--   * timestamps are naive UTC (see app/models/task.py:utcnow).
--   * every identifier is <= 30 characters so Oracle accepts it unquoted.

CREATE TABLE tasks (
    id              VARCHAR(36)  NOT NULL,
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    status          VARCHAR(20)  NOT NULL,
    priority        VARCHAR(20)  NOT NULL,
    criticality     VARCHAR(20),
    impact_size     VARCHAR(20),
    due_date        DATE,
    assignee        VARCHAR(200),
    project         VARCHAR(200),
    -- JSONB here, CLOB on Oracle. Never filter or index *inside* these
    -- columns; every field the app filters on is a real column.
    labels          JSONB        NOT NULL,
    source_provider VARCHAR(32)  NOT NULL,
    source_ref      VARCHAR(255) NOT NULL,
    external_refs   JSONB        NOT NULL,
    raw_payload     JSONB,
    destination     VARCHAR(32),
    created_at      TIMESTAMP    NOT NULL,
    updated_at      TIMESTAMP    NOT NULL,
    CONSTRAINT pk_tasks PRIMARY KEY (id),
    -- Idempotency: re-importing the same item from the same source updates the
    -- existing row instead of creating a second one.
    CONSTRAINT uq_tasks_source UNIQUE (source_provider, source_ref)
);

CREATE INDEX ix_tasks_due_date ON tasks (due_date);
CREATE INDEX ix_tasks_status   ON tasks (status);
CREATE INDEX ix_tasks_project  ON tasks (project);

-- Per-project default destination. Resolution order lives in
-- app/services/routing.py: task -> project default -> "local".
CREATE TABLE project_routes (
    id          VARCHAR(36)  NOT NULL,
    project     VARCHAR(200) NOT NULL,
    destination VARCHAR(32)  NOT NULL,
    created_at  TIMESTAMP    NOT NULL,
    updated_at  TIMESTAMP    NOT NULL,
    CONSTRAINT pk_project_routes PRIMARY KEY (id),
    CONSTRAINT uq_project_routes_project UNIQUE (project)
);
