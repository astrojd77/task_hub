"""initial task schema

Revision ID: 169a9a8ab8ae
Revises:
Create Date: 2026-07-26 16:49:57.036853

Portable across SQLite / Postgres / Oracle:
  * ``id`` is VARCHAR(36) holding a Python-generated uuid4, not a DB UUID type.
  * JSON columns go through PortableJSON, which renders JSONB on Postgres,
    CLOB on Oracle and generic JSON elsewhere.
  * No CHECK constraints on the enum columns — the canonical scales are tunable
    and are enforced server-side in the Pydantic layer.
  * Every identifier is <= 30 characters so Oracle accepts it unquoted.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.types

revision: str = "169a9a8ab8ae"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("criticality", sa.String(length=20), nullable=True),
        sa.Column("impact_size", sa.String(length=20), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("assignee", sa.String(length=200), nullable=True),
        sa.Column("project", sa.String(length=200), nullable=True),
        sa.Column("labels", app.db.types.PortableJSON(), nullable=False),
        sa.Column("source_provider", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=False),
        sa.Column("external_refs", app.db.types.PortableJSON(), nullable=False),
        sa.Column("raw_payload", app.db.types.PortableJSON(), nullable=True),
        sa.Column("destination", sa.String(length=32), nullable=True),
        sa.Column("created_at", app.db.types.UTCDateTime, nullable=False),
        sa.Column("updated_at", app.db.types.UTCDateTime, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
        sa.UniqueConstraint("source_provider", "source_ref", name="uq_tasks_source"),
    )
    op.create_index("ix_tasks_due_date", "tasks", ["due_date"], unique=False)
    op.create_index("ix_tasks_project", "tasks", ["project"], unique=False)
    op.create_index("ix_tasks_status", "tasks", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_project", table_name="tasks")
    op.drop_index("ix_tasks_due_date", table_name="tasks")
    op.drop_table("tasks")
