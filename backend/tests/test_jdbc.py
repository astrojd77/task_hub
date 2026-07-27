"""SQLAlchemy URL -> Flyway JDBC target.

Worth real tests: a silent mistranslation here points the migration job at a
different database than the app, which is the sort of thing you discover in
production.
"""

from __future__ import annotations

import pytest

from app.db.jdbc import UnsupportedDialect, to_flyway_target


def test_postgres_url():
    t = to_flyway_target("postgresql+psycopg://taskhub:pw@db.example.com:5432/taskhub")

    assert t.url == "jdbc:postgresql://db.example.com:5432/taskhub"
    assert (t.user, t.password) == ("taskhub", "pw")
    assert t.migration_dir == "postgresql"


def test_postgres_default_port():
    t = to_flyway_target("postgresql+psycopg://u:p@localhost/taskhub")
    assert t.url == "jdbc:postgresql://localhost:5432/taskhub"


def test_oracle_service_name_uses_ezconnect():
    """//host:port/service needs no tnsnames.ora in the migration container."""
    t = to_flyway_target("oracle+oracledb://u:p@ora.example.com:1521/?service_name=FREEPDB1")

    assert t.url == "jdbc:oracle:thin:@//ora.example.com:1521/FREEPDB1"
    assert t.migration_dir == "oracle"


def test_oracle_sid_form():
    t = to_flyway_target("oracle+oracledb://u:p@ora.example.com:1521/XE")
    assert t.url == "jdbc:oracle:thin:@ora.example.com:1521:XE"


def test_oracle_without_service_or_sid_is_rejected():
    with pytest.raises(UnsupportedDialect, match="service_name"):
        to_flyway_target("oracle+oracledb://u:p@ora.example.com:1521/")


def test_sqlite_relative_and_absolute_paths():
    assert to_flyway_target("sqlite+pysqlite:///./dev.db").url == "jdbc:sqlite:./dev.db"
    assert to_flyway_target("sqlite+pysqlite:////tmp/x.db").url == "jdbc:sqlite:/tmp/x.db"


def test_in_memory_sqlite_cannot_be_migrated():
    """Nothing would persist — better to say so than to no-op."""
    with pytest.raises(UnsupportedDialect, match="in-memory"):
        to_flyway_target("sqlite+pysqlite:///:memory:")


def test_unsupported_dialect_lists_the_supported_ones():
    with pytest.raises(UnsupportedDialect, match="postgresql"):
        to_flyway_target("mysql+pymysql://u:p@host/db")


def test_percent_encoded_password_is_decoded():
    """Passwords with @ or / must be encoded in the URL and decoded for Flyway."""
    t = to_flyway_target("postgresql+psycopg://u:p%40ss%2Fword@host:5432/db")
    assert t.password == "p@ss/word"


def test_password_is_redacted_by_default():
    t = to_flyway_target("postgresql+psycopg://u:hunter2@host:5432/db")

    assert t.as_dict()["password"] == "***"
    assert t.as_dict(redact=False)["password"] == "hunter2"
