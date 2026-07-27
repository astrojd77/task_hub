-- Task Hub baseline schema — SQLite (local development only)
--
-- Not a deployment target. It exists so the zero-setup local loop goes through
-- the same migration tool as everything else, rather than quietly creating
-- tables from the models and drifting away from the SQL that ships.
--
-- SQLite applies type affinity rather than strict types, so JSON and TIMESTAMP
-- below are affinity hints; SQLAlchemy does the real conversion.

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
    labels          JSON         NOT NULL,
    source_provider VARCHAR(32)  NOT NULL,
    source_ref      VARCHAR(255) NOT NULL,
    external_refs   JSON         NOT NULL,
    raw_payload     JSON,
    destination     VARCHAR(32),
    created_at      DATETIME     NOT NULL,
    updated_at      DATETIME     NOT NULL,
    CONSTRAINT pk_tasks PRIMARY KEY (id),
    CONSTRAINT uq_tasks_source UNIQUE (source_provider, source_ref)
);

CREATE INDEX ix_tasks_due_date ON tasks (due_date);
CREATE INDEX ix_tasks_status   ON tasks (status);
CREATE INDEX ix_tasks_project  ON tasks (project);

CREATE TABLE project_routes (
    id          VARCHAR(36)  NOT NULL,
    project     VARCHAR(200) NOT NULL,
    destination VARCHAR(32)  NOT NULL,
    created_at  DATETIME     NOT NULL,
    updated_at  DATETIME     NOT NULL,
    CONSTRAINT pk_project_routes PRIMARY KEY (id),
    CONSTRAINT uq_project_routes_project UNIQUE (project)
);
