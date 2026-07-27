"""Translate the app's SQLAlchemy URL into what Flyway needs.

Flyway speaks JDBC; everything else here speaks SQLAlchemy. Keeping one
``DATABASE_URL`` as the single source of truth means dev, prod and the
migration job cannot end up pointed at different databases — which is the
failure this module exists to prevent.

Run it directly to see what Flyway would be handed:

    python -m app.db.jdbc                    # uses DATABASE_URL
    python -m app.db.jdbc --field url        # just the JDBC URL
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from urllib.parse import unquote

from sqlalchemy.engine import make_url


class UnsupportedDialect(ValueError):
    """No Flyway migrations exist for this database."""


#: SQLAlchemy dialect -> the folder under db/migration holding its SQL.
MIGRATION_DIRS: dict[str, str] = {
    "postgresql": "postgresql",
    "oracle": "oracle",
    "sqlite": "sqlite",
}


@dataclass(frozen=True)
class FlywayTarget:
    url: str
    user: str
    password: str
    dialect: str

    @property
    def migration_dir(self) -> str:
        return MIGRATION_DIRS[self.dialect]

    def as_dict(self, *, redact: bool = True) -> dict[str, str]:
        return {
            "url": self.url,
            "user": self.user,
            "password": "***" if redact and self.password else self.password,
            "dialect": self.dialect,
            "migration_dir": self.migration_dir,
        }


def to_flyway_target(database_url: str) -> FlywayTarget:
    """Convert a SQLAlchemy URL into Flyway's JDBC equivalent."""
    url = make_url(database_url)
    dialect = url.get_backend_name()

    if dialect not in MIGRATION_DIRS:
        raise UnsupportedDialect(
            f"no Flyway migrations for {dialect!r} — supported: {', '.join(sorted(MIGRATION_DIRS))}"
        )

    user = url.username or ""
    password = unquote(url.password) if url.password else ""

    if dialect == "postgresql":
        host = url.host or "localhost"
        port = url.port or 5432
        jdbc = f"jdbc:postgresql://{host}:{port}/{url.database or ''}"

    elif dialect == "oracle":
        host = url.host or "localhost"
        port = url.port or 1521
        # SQLAlchemy already parsed the query string; repeated keys arrive as
        # a tuple, so take the first.
        raw_service = url.query.get("service_name")
        service_name = raw_service[0] if isinstance(raw_service, tuple) else raw_service
        if service_name:
            # The //host:port/service form is the modern EZConnect syntax and
            # avoids needing a tnsnames.ora in the migration container.
            jdbc = f"jdbc:oracle:thin:@//{host}:{port}/{service_name}"
        elif url.database:
            # A bare database component in an Oracle URL is the SID.
            jdbc = f"jdbc:oracle:thin:@{host}:{port}:{url.database}"
        else:
            raise UnsupportedDialect(
                "an Oracle URL needs either ?service_name=... or a SID path component"
            )

    else:  # sqlite
        # SQLAlchemy writes sqlite:///relative.db and sqlite:////absolute.db;
        # url.database carries the path either way. An in-memory database has
        # either no path or the literal ":memory:".
        if not url.database or url.database == ":memory:":
            raise UnsupportedDialect(
                "Flyway cannot migrate an in-memory SQLite database — nothing would persist"
            )
        jdbc = f"jdbc:sqlite:{url.database}"

    return FlywayTarget(url=jdbc, user=user, password=password, dialect=dialect)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show the Flyway target for a DATABASE_URL.")
    parser.add_argument(
        "database_url",
        nargs="?",
        help="defaults to the DATABASE_URL the app is configured with",
    )
    parser.add_argument(
        "--field",
        choices=["url", "user", "password", "dialect", "migration_dir"],
        help="print one value instead of the whole object",
    )
    args = parser.parse_args(argv)

    if args.database_url:
        database_url = args.database_url
    else:
        from app.core.config import get_settings

        database_url = get_settings().database_url

    try:
        target = to_flyway_target(database_url)
    except UnsupportedDialect as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.field:
        # Unredacted: this branch is what the migrate script consumes.
        print(target.as_dict(redact=False)[args.field])
    else:
        print(json.dumps(target.as_dict(), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
