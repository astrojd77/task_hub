# Task Hub

A task/project management hub for engineering leadership. It imports work items
from targeted sources, holds them as **drafts for review**, commits reviewed
tasks to a canonical store, shows a unified calendar of due dates, and routes
each task to a selectable destination platform.

Two properties define the architecture:

1. **Sources and destinations are pluggable adapters** behind common interfaces
   and a registry. Adding a platform means writing one adapter and registering
   it — never touching core.
2. **Nothing is created without review.** Every source produces *draft* tasks;
   the user reviews and completes them before anything is committed.

---

## Status

| Phase | Scope | State |
| ----- | ----- | ----- |
| 0 | Scaffold, canonical model, registry, commit pipeline | ✅ done |
| 1 | CSV source + review table + local destination | ✅ done |
| 2 | Calendar view | ⬜ next |
| 3 | Watch / notifications view | ⬜ |
| 4 | Jira source (targeted) + review modal | ⬜ |
| 5 | Email (`.msg` / `.eml`) drop source | ⬜ |
| 6 | Destination routing + Jira push | ⬜ |

Deployment to OpenShift is available now — see
[`deploy/openshift/`](deploy/openshift/README.md).

---

## Run it

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

cp ../.env.example ../.env        # then edit if you want Postgres/Oracle
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000
```

API docs: <http://127.0.0.1:8000/docs>

### Frontend

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

Vite proxies `/api` to `127.0.0.1:8000`, so there is no base-URL config and no
CORS in the dev loop.

### Dev database (optional)

SQLite is the zero-setup default. For Postgres:

```bash
docker compose up -d db
DATABASE_URL=postgresql+psycopg://taskhub:taskhub@localhost:5432/taskhub \
  backend/.venv/bin/alembic upgrade head
```

### Tests

```bash
cd backend && .venv/bin/python -m pytest
```

### Try the import

`examples/sample_tasks.csv` exercises the interesting cases — mixed native
vocabularies (`P1`, `Sev 1`, `XL`), and one row with no criticality, impact or
due date so the review screen has something to ask you for.

---

## Deployment

The container image serves the API *and* the built SPA from one origin, so
production is a single Deployment with no CORS configuration.

```bash
docker build -t task-hub .
docker run -p 8080:8080 -e DATABASE_URL=... task-hub
```

For OpenShift — including the arbitrary-UID constraints, the migration Job and
both build paths — see [`deploy/openshift/`](deploy/openshift/README.md).

In dev the static directory does not exist, so the API serves only `/api` and
Vite serves the frontend. Same code, no build-time switch.

---

## Architecture

Hub-and-spoke around one canonical `Task`. Sources map *into* a draft;
destinations map *out of* a committed task. Core knows about zero specific
platforms.

```
Source.fetch()  ->  DraftTask[]        parsed, NOT persisted
      -> review UI (modal for one, table for many)
      -> user edits / fills required fields / selects rows
      -> POST /api/commit  ->  validated  ->  Task rows (idempotent upsert)
```

### The three prioritization axes

These are deliberately independent and must not be collapsed:

| Field | Question it answers | Scale |
| ----- | ------------------- | ----- |
| `priority` | Urgency — what do I do first? | low, medium, high, urgent |
| `criticality` | Severity — how bad if it fails or slips? | low, medium, high, critical |
| `impact_size` | Blast radius — how much is affected? | xs, s, m, l, xl |

Most sources supply at most `priority`. `criticality` and `impact_size` are
usually absent from CSV/Jira/email — they are exactly what the review popup
exists to capture before commit.

### Layout

```
backend/app/
  core/         config, canonical enums
  db/           base metadata, portable column types, session
  models/       SQLAlchemy Task
  schemas/      DraftTask (permissive) / TaskCommitIn (strict) / TaskOut
  providers/
    base.py       SourceProvider + DestinationProvider protocols
    registry.py   self-registration, config-driven enable/disable
    sources/      one module per inbound platform
    destinations/ one module per outbound platform
  services/     commit (the only writer), shared filters
  api/          FastAPI routers
frontend/src/
  api/          typed client mirroring the backend schemas
```

### Adding a platform

Write one module under `providers/sources/` or `providers/destinations/`,
decorate the class with `@source` / `@destination`, and import it in
`providers/__init__.py`. Add its id to `ENABLED_SOURCES` /
`ENABLED_DESTINATIONS`.

That is the whole change. The calendar, task list, watch view and normalizer
must not need edits — if a new adapter forces a core change, the abstraction is
wrong and the abstraction gets fixed, not worked around. `/api/providers` feeds
the UI's pickers, so a new adapter appears in the frontend with no frontend
change.

### Commit semantics

* **Idempotency key** is `(source_provider, source_ref)` — a CSV row hash, a
  Jira issue key, an email `Message-ID`. Re-importing updates; it never
  duplicates.
* **A committed draft is the full desired state** for its task. Re-importing
  with a field unset clears that field. This keeps commit predictable; the
  cost is that a re-import must not silently discard review work, so from
  phase 1 the review UI pre-fills drafts from the existing task, putting the
  decision in front of the user rather than in a merge rule.
* **Validation is server-authoritative.** Blank titles and off-scale enum
  values are rejected with a 422 whatever the UI does. Missing `due_date` or
  `criticality` come back as *warnings* alongside the committed tasks.
* `local` is always an available destination, even if config omits it —
  otherwise a commit would have nowhere to go.

---

## Database portability

The schema runs on SQLite and Postgres in dev and **Oracle in prod**. Switching
is an env change only (`DATABASE_URL`); `python-oracledb` runs in thin mode, so
no Oracle Instant Client install is needed.

What that costs us, and how it is handled:

| Hazard | Handling |
| ------ | -------- |
| Postgres-only JSONB | `PortableJSON` renders JSONB on Postgres, CLOB (with Python-side (de)serialisation) on Oracle, generic JSON elsewhere |
| `gen_random_uuid()` / native UUID type | uuid4 generated in Python, stored as `VARCHAR2(36)` |
| Oracle has no BOOLEAN pre-23c | no boolean columns yet; use SQLAlchemy `Boolean` (→ `NUMBER(1)`), never literal `true`/`false` in SQL |
| Oracle 30-char identifier cap | naming convention plus explicit short names — every generated identifier is under 30 chars |
| Oracle `DateTime` → `DATE` (second precision only) | `UTCDateTime` renders `TIMESTAMP` on Oracle; list ordering also has an `id` tiebreaker |
| Postgres-only `ILIKE` | SQLAlchemy `ilike()`, which degrades to `lower() LIKE lower()` elsewhere |

Because the Oracle JSON variant is a CLOB, never filter or index *inside* those
columns. Every field the app filters on is a real column.

All timestamps are naive UTC.

### Verifying against Oracle

Rendering the migration for the Oracle dialect needs no database:

```bash
cd backend
DATABASE_URL="oracle+oracledb://u:p@localhost:1521/?service_name=X" \
  .venv/bin/alembic upgrade head --sql
```

For a real run against Oracle Free:

```bash
docker compose --profile oracle up -d oracle   # large image, slow first boot
DATABASE_URL="oracle+oracledb://taskhub:taskhub@localhost:1521/?service_name=FREEPDB1" \
  backend/.venv/bin/alembic upgrade head
```

Migrations must be applied against an Oracle target before a release is
considered prod-ready — SQLite-only testing hides Oracle DDL issues.

---

## Configuration

All config is env-driven; see [`.env.example`](.env.example). No secrets are
committed.

| Variable | Purpose |
| -------- | ------- |
| `DATABASE_URL` | SQLAlchemy URL — the only dev/prod difference |
| `CORS_ORIGINS` | comma-separated allowed origins |
| `ENABLED_SOURCES` | which inbound adapters are live |
| `ENABLED_DESTINATIONS` | which outbound adapters are live (`local` always on) |
| `STATIC_DIR` | built SPA to serve; when absent the API serves only `/api` |

## API

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET | `/api/health` | liveness + dialect (never credentials) |
| GET | `/api/ready` | readiness — runs `SELECT 1` against the database |
| GET | `/api/enums` | canonical scales, so the UI hardcodes none |
| GET | `/api/providers` | registered + enabled adapters and their capabilities |
| GET | `/api/tasks` | committed tasks, with the shared filter facets |
| GET | `/api/tasks/facets` | distinct values behind the filter dropdowns |
| GET | `/api/tasks/{id}` | one task |
| DELETE | `/api/tasks/{id}` | remove a task |
| POST | `/api/sources/{id}/drafts` | parse a source's input into drafts — persists nothing |
| POST | `/api/commit` | **the only door into the task store** |
