---
applyTo: "backend/db/migration/**/*.sql,backend/app/models/**/*.py,backend/app/db/**/*.py"
---

# Database

Runs on SQLite and Postgres in dev and **Oracle in production**. Switching is an
env change only (`DATABASE_URL`). `python-oracledb` runs in thin mode — no
Oracle Instant Client on the image.

## Migrations are Flyway, not Alembic

Hand-written SQL, one folder per dialect:

```
backend/db/migration/{postgresql,oracle,sqlite}/
  V1__baseline_schema.sql
  V2__configurable_fields.sql
  V3__summary_and_source_mappings.sql
```

The short text field is `summary`, not `title` — that is what Jira and email
already call it. `description` is the long one.

**A schema change means editing all three files.** There is no autogenerate.
`backend/tests/test_schema_parity.py` compares the migrated schema against the
SQLAlchemy metadata and fails CI if they drift — run it after any schema work:

```bash
./scripts/migrate.sh
PARITY_DATABASE_URL="$DATABASE_URL" .venv/bin/python -m pytest tests/test_schema_parity.py
```

Naming: `V<n>__snake_case_description.sql`, sequential, **never edit an applied
migration** — Flyway validates checksums and will refuse to run.

Never add `clean` to any automated Flyway invocation. It drops every object in
the schema.

Never set `baselineOnMigrate` as a default. On a non-empty schema with no
history table it marks migrations as applied *without running them* and reports
success.

## Oracle rules

| Rule | Why |
| ---- | --- |
| Identifiers ≤ 30 characters | Oracle's cap; longer names fail unquoted |
| `VARCHAR2(n CHAR)` | CHAR semantics, so length is characters not bytes under AL32UTF8 |
| `CLOB` for JSON | Oracle only gained native JSON in 21c; `app/db/types.py` serialises in Python for this dialect |
| `TIMESTAMP`, never `DATE`, for timestamps | Oracle `DATE` has second precision, so bulk-import rows tie and sort unstably |
| uuid4 generated in Python, stored `VARCHAR2(36)` | no `gen_random_uuid()`, and no portable native UUID type |
| No `ILIKE` | Postgres-only; SQLAlchemy's `ilike()` degrades to `lower() LIKE lower()` |
| No literal `true`/`false` | Oracle had no BOOLEAN before 23c; let SQLAlchemy map `Boolean` to `NUMBER(1)` |
| Chunk `IN` lists at 500 | Oracle rejects more than 1000 entries (ORA-01795) |

Never filter or index *inside* a JSON column — on Oracle it is a CLOB. Every
field the app filters on is a real column.

All timestamps are naive UTC (`app/models/task.py:utcnow`).

## Before a release

Rendering DDL is not the same as running it. Apply the migrations against a real
Oracle instance:

```bash
docker compose --profile oracle up -d oracle
DATABASE_URL="oracle+oracledb://taskhub:taskhub@localhost:1521/?service_name=FREEPDB1" \
  ./scripts/migrate.sh
```
