"""Declarative base and shared metadata conventions.

Oracle folds unquoted identifiers to upper case and (pre-12.2) capped names at
30 characters. Every generated constraint/index name below therefore has to fit
in 30 chars, which is why the naming convention uses ``column_0_name`` rather
than ``column_0_N_name`` — and why anything at risk of overflowing is named
explicitly on the model.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
