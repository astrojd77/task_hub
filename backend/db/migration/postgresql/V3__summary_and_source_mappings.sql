-- Rename title -> summary, and add per-source field mapping — PostgreSQL
--
-- "Summary" is what Jira and email already call this field, and what the
-- people using this call it. It is the same column, renamed — not a third
-- text field, because no source has anything to fill a third one from.
--
-- source_mappings answers, for one import flow and one canonical field:
--   * which input feeds it        (source_expr)
--   * how that input's values translate (value_map)
--
-- What source_expr *means* is the adapter's business: a CSV column header, a
-- Jira field id, an email part. Core never interprets it.

ALTER TABLE tasks RENAME COLUMN title TO summary;

CREATE TABLE source_mappings (
    id              VARCHAR(36) NOT NULL,
    source_provider VARCHAR(32) NOT NULL,
    -- Canonical field this feeds: 'summary', 'criticality', 'type', ...
    field_key       VARCHAR(50) NOT NULL,
    -- Adapter-specific: CSV column header, Jira field id, email part.
    -- Null means "this field is mapped by value rules only".
    source_expr     VARCHAR(200),
    -- {"sev 1": "critical", "escalated": "high"} — native value (lowercased)
    -- to canonical value. Empty when the adapter's built-in table suffices.
    value_map       JSONB       NOT NULL,
    created_at      TIMESTAMP   NOT NULL,
    updated_at      TIMESTAMP   NOT NULL,
    CONSTRAINT pk_source_mappings PRIMARY KEY (id),
    -- One mapping per field per flow.
    CONSTRAINT uq_source_mappings UNIQUE (source_provider, field_key)
);
