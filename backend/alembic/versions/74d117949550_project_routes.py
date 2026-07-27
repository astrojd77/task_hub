"""project routes

Revision ID: 74d117949550
Revises: 169a9a8ab8ae
Create Date: 2026-07-26 21:22:57.614887

Per-project default destination. ``project`` is unique so a project has exactly
one default; the resolution order (task -> project -> local) lives in
app/services/routing.py.

Autogenerate emitted a bare ``oracle.TIMESTAMP()`` here without importing the
dialect, which would have failed on import. Uses the shared ``UTCDateTime``
instead, matching the tasks table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.types

revision: str = "74d117949550"
down_revision: str | None = "169a9a8ab8ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_routes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project", sa.String(length=200), nullable=False),
        sa.Column("destination", sa.String(length=32), nullable=False),
        sa.Column("created_at", app.db.types.UTCDateTime, nullable=False),
        sa.Column("updated_at", app.db.types.UTCDateTime, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_routes")),
        sa.UniqueConstraint("project", name=op.f("uq_project_routes_project")),
    )


def downgrade() -> None:
    op.drop_table("project_routes")
