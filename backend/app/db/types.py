"""Portable column types.

The schema must run unchanged on SQLite (dev), Postgres (dev/staging) and
Oracle (prod), so nothing here may be Postgres-only.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import CLOB, JSON, DateTime, Dialect
from sqlalchemy.dialects import oracle as _oracle
from sqlalchemy.types import TypeDecorator

#: Oracle maps a plain ``DateTime`` to ``DATE``, which has only second
#: precision — enough to make a bulk commit's rows tie on ``created_at`` and
#: sort unstably. ``TIMESTAMP`` keeps sub-second precision there; every other
#: dialect gets its usual DATETIME/TIMESTAMP.
#:
#: All timestamps in this schema are naive UTC (see ``app.models.task.utcnow``).
UTCDateTime = DateTime().with_variant(_oracle.TIMESTAMP(), "oracle")


class PortableJSON(TypeDecorator):
    """JSON that maps to the best native type per dialect.

    * Postgres — ``JSONB``
    * Oracle   — ``CLOB`` with Python-side (de)serialisation. Oracle only grew a
      native ``JSON`` type in 21c; CLOB works on every supported version and
      ``oracledb`` thin mode handles it without a client install.
    * Others   — SQLAlchemy's generic ``JSON``

    Because the Oracle variant is a plain CLOB, never write SQL that indexes or
    filters *inside* these columns. They are provenance and reference bags, and
    every field the app filters on is a real column.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB

            return dialect.type_descriptor(JSONB())
        if dialect.name == "oracle":
            return dialect.type_descriptor(CLOB())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if dialect.name == "oracle":
            return None if value is None else json.dumps(value)
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if dialect.name == "oracle" and isinstance(value, str):
            if not value:
                return None
            return json.loads(value)
        return value
