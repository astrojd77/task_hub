"""Does the Flyway SQL still match the SQLAlchemy models?

Moving to Flyway traded autogenerate for hand-written, DBA-reviewable SQL. The
cost is that nothing stops ``db/migration/*.sql`` drifting from
``app/models/*.py`` — a column added to a model and forgotten in the SQL would
otherwise surface as a runtime error in production.

This is the replacement for ``alembic check``. It runs against a database that
Flyway actually migrated, so it tests the shipped SQL rather than a rendering
of it.

    ./scripts/migrate.sh
    PARITY_DATABASE_URL="$DATABASE_URL" .venv/bin/python -m pytest tests/test_schema_parity.py

CI does this against PostgreSQL on every push; run it against Oracle before a
release. Skipped when PARITY_DATABASE_URL is unset, so the normal suite stays
dependency-free.

Structure is compared, not column *types*: those legitimately differ per
dialect (JSONB vs CLOB, TIMESTAMP vs DATETIME) and are the whole reason the SQL
is maintained per dialect. Names, nullability, keys and indexes must match
everywhere.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect

from app.db.base import Base
from app.models import ProjectRoute, Task

PARITY_URL = os.environ.get("PARITY_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not PARITY_URL,
    reason="set PARITY_DATABASE_URL to a Flyway-migrated database to run schema parity checks",
)


@pytest.fixture(scope="module")
def inspector():
    engine = create_engine(PARITY_URL, future=True)
    try:
        yield inspect(engine)
    finally:
        engine.dispose()


def _model_tables() -> dict:
    return dict(Base.metadata.tables)


def test_every_model_table_exists(inspector):
    live = set(inspector.get_table_names())
    expected = set(_model_tables())

    missing = expected - live
    assert not missing, f"tables in the models but not in the migrated database: {sorted(missing)}"


def test_no_unexpected_tables(inspector):
    """Catches a table dropped from the models but left in the SQL."""
    live = {t for t in inspector.get_table_names() if not t.startswith("flyway_")}
    extra = live - set(_model_tables())

    assert not extra, f"tables in the database with no model: {sorted(extra)}"


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_columns_match(inspector, table_name):
    live = {c["name"]: c for c in inspector.get_columns(table_name)}
    expected = _model_tables()[table_name].columns

    missing = {c.name for c in expected} - set(live)
    assert not missing, f"{table_name}: columns missing from the migration SQL: {sorted(missing)}"

    extra = set(live) - {c.name for c in expected}
    assert not extra, f"{table_name}: columns in the database with no model: {sorted(extra)}"


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_nullability_matches(inspector, table_name):
    live = {c["name"]: c["nullable"] for c in inspector.get_columns(table_name)}

    mismatched = [
        f"{column.name}: model={'NULL' if column.nullable else 'NOT NULL'}, "
        f"db={'NULL' if live[column.name] else 'NOT NULL'}"
        for column in _model_tables()[table_name].columns
        if column.name in live and column.nullable != live[column.name]
    ]
    assert not mismatched, f"{table_name}: nullability differs — {mismatched}"


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_primary_key_matches(inspector, table_name):
    live = set(inspector.get_pk_constraint(table_name).get("constrained_columns") or [])
    expected = {c.name for c in _model_tables()[table_name].primary_key}

    assert live == expected, f"{table_name}: primary key differs"


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_unique_constraints_match(inspector, table_name):
    """Idempotency depends on uq_tasks_source actually existing."""
    live = {
        tuple(sorted(uc["column_names"])) for uc in inspector.get_unique_constraints(table_name)
    }
    # Some dialects report a unique constraint as a unique index instead.
    live |= {
        tuple(sorted(ix["column_names"]))
        for ix in inspector.get_indexes(table_name)
        if ix.get("unique") and ix.get("column_names")
    }

    expected = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in _model_tables()[table_name].constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    missing = expected - live
    assert not missing, f"{table_name}: unique constraints missing from the SQL: {sorted(missing)}"


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_indexes_match(inspector, table_name):
    live = {
        tuple(sorted(ix["column_names"]))
        for ix in inspector.get_indexes(table_name)
        if ix.get("column_names")
    }
    expected = {
        tuple(sorted(c.name for c in index.columns))
        for index in _model_tables()[table_name].indexes
    }

    missing = expected - live
    assert not missing, (
        f"{table_name}: indexes missing from the SQL: {sorted(missing)} — "
        "these back the calendar and filter queries"
    )
