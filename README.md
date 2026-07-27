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
| 2 | Calendar view | ✅ done |
| 3 | Watch / notifications view | ✅ done |
| 4 | Jira source (targeted) + review modal | ✅ done |
| 5 | Email (`.msg` / `.eml`) drop source | ✅ done |
| 6 | Destination routing + Jira push | ✅ done |
| 7 | Re-sync, delivered digests, more destinations | ⬜ later |

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

cd .. && ./scripts/migrate.sh     # Flyway; dialect derived from DATABASE_URL
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
```

Flyway runs from its official container image, so no local Java is needed.

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
DATABASE_URL=postgresql+psycopg://taskhub:taskhub@localhost:5432/taskhub ./scripts/migrate.sh
```

### Tests

```bash
cd backend && .venv/bin/python -m pytest
```

Full setup, configuration and troubleshooting: [`docs/SETUP.md`](docs/SETUP.md).

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
  models/       SQLAlchemy Task, ProjectRoute
  schemas/      DraftTask (permissive) / TaskCommitIn (strict) / TaskOut
  providers/
    base.py       SourceProvider + DestinationProvider protocols
    registry.py   self-registration, config-driven enable/disable
    jira_client.py shared REST v3 client + ADF handling
    sources/      csv, jira, email
    destinations/ local, jira
  services/     commit (the only writer), filters, watch, routing, drafts
  api/          FastAPI routers
frontend/src/
  api/          typed client mirroring the backend schemas
  import/       per-source panels + shared draft review
  review/       ReviewTable (many) and ReviewModal (one)
  filters/      one filter model shared by all three views
  tasks/ calendar/ watch/
```

### Sources

| Source | Targeting | Idempotency key |
| ------ | --------- | --------------- |
| CSV | a file, with column mapping | row hash of the *original* row, or an id column if present |
| Jira | **one issue key or one JQL query** — never a blanket pull | issue key |
| Email | a saved `.msg` / `.eml`, parsed locally | `Message-ID`, falling back to a content hash |

Email has **no Outlook or Graph connection**. Dragging straight out of the
Outlook desktop app is out of scope — it exposes a virtual file the browser
usually cannot read — so the picker fallback covers that: save the message
first, then drop or pick it.

### Routing

Destination resolves most-specific-first: **task → project default → `local`**.
`GET /api/tasks/{id}/destination` reports which rule won, because "resolved:
jira" is less useful than "jira, because it is the default for project
Platform".

One guardrail: a task whose `source_provider` matches its destination cannot be
pushed as a *new* item — that would silently duplicate the issue it came from.
Updating the original is allowed and is what a second push does. The rule is
written against any adapter that is both a source and a destination, not just
Jira.

### The watch score

Every knob lives in `WatchWeights` in `app/services/watch.py`:

```
score = criticality_weight + impact_weight + due_urgency + (blocked ? +2 : 0)
```

Each row returns its own breakdown (`"criticality high +3"`, `"overdue by 2d
+5"`) and the API returns the weight table, so the ranking can be explained and
tuned rather than trusted. Done work is excluded from the view entirely —
including from overdue, where a completed-but-late task is noise.

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

### Migrations

Flyway, with hand-written SQL per dialect:

```
backend/db/migration/{postgresql,oracle,sqlite}/V1__baseline_schema.sql
```

`./scripts/migrate.sh` derives the dialect, JDBC URL and credentials from
`DATABASE_URL`, so there is one place a database is configured.

There is no autogenerate, so a schema change means editing all three files.
`tests/test_schema_parity.py` is the safety net: it compares a Flyway-migrated
database against the SQLAlchemy metadata and fails CI on drift.

```bash
./scripts/migrate.sh
cd backend
PARITY_DATABASE_URL="$DATABASE_URL" .venv/bin/python -m pytest tests/test_schema_parity.py
```

Verify against real Oracle before a release — rendering DDL is not running it:

```bash
docker compose --profile oracle up -d oracle   # large image, slow first boot
DATABASE_URL="oracle+oracledb://taskhub:taskhub@localhost:1521/?service_name=FREEPDB1" \
  ./scripts/migrate.sh
```

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
| `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` | Jira credentials — server-side only, never sent from the browser |
| `JIRA_PROJECT_KEY`, `JIRA_ISSUE_TYPE` | where pushed issues are created |
| `JIRA_CRITICALITY_FIELD`, `JIRA_IMPACT_FIELD` | optional custom fields carrying criticality / impact |

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
| GET | `/api/watch` | computed heads-up, scored and explained |
| POST | `/api/sources/{id}/drafts` | parse a source's input into drafts — persists nothing |
| POST | `/api/commit` | **the only door into the task store** |
| GET/PUT | `/api/routes` | per-project default destinations |
| GET/PUT | `/api/tasks/{id}/destination` | per-task destination, and how it resolves |
| POST | `/api/tasks/{id}/push` | send a task to its destination |
