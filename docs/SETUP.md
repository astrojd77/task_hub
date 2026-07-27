# Setup

Everything needed to run Task Hub locally, migrate a database, and configure the
optional integrations.

- [Prerequisites](#prerequisites)
- [First run](#first-run)
- [Database and migrations](#database-and-migrations)
- [Configuration](#configuration)
- [Jira](#jira)
- [Email](#email)
- [Configuring fields and defaults](#configuring-fields-and-defaults)
- [Day-to-day commands](#day-to-day-commands)
- [Changing the schema](#changing-the-schema)
- [Deploying](#deploying)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Why | Notes |
| ---- | --- | ----- |
| Python 3.11+ | backend | 3.13 in CI and in the image |
| Node 20+ | frontend | 22 in CI |
| Docker or Podman | Flyway migrations, dev databases | Flyway runs as a container, so no local Java |
| `oc` | OpenShift deploys only | not needed for local work |

Java is **not** required — Flyway runs from its official image.

---

## First run

```bash
git clone https://github.com/astrojd77/task_hub.git
cd task_hub
cp .env.example .env
```

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Add the driver for whichever database you plan to use:

```bash
.venv/bin/pip install -e ".[dev,postgres]"   # Postgres
.venv/bin/pip install -e ".[dev,oracle]"     # Oracle (thin mode, no client install)
```

### Create the schema

SQLite is the zero-setup default:

```bash
cd ..
./scripts/migrate.sh
```

This derives the dialect, JDBC URL and credentials from `DATABASE_URL` and runs
Flyway in a container. Expect `Successfully applied 1 migration`.

### Run it

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to port 8000, so there is no
base URL to configure and no CORS in the dev loop.

API docs are at <http://127.0.0.1:8000/docs>.

### Check it works

Import `examples/sample_tasks.csv` from the Import tab. It deliberately mixes
native vocabularies (`P1`, `Sev 1`, `XL`) and leaves one row without
criticality, impact or a due date, so the review screen has something to ask
you for. Commit, then import the same file again: you should get **0 created,
5 updated**.

---

## Database and migrations

Migrations are **Flyway SQL**, hand-written per dialect:

```
backend/db/migration/
  postgresql/V1__baseline_schema.sql
  oracle/V1__baseline_schema.sql
  sqlite/V1__baseline_schema.sql
```

`./scripts/migrate.sh` picks the right folder from `DATABASE_URL`. It accepts
any Flyway command:

```bash
./scripts/migrate.sh            # migrate (default)
./scripts/migrate.sh info       # what's applied
./scripts/migrate.sh validate   # do checksums still match?
```

### Postgres

```bash
docker compose up -d db
DATABASE_URL=postgresql+psycopg://taskhub:taskhub@localhost:5432/taskhub ./scripts/migrate.sh
```

Or the compose shortcut, which is hardwired to that database:

```bash
docker compose --profile migrate run --rm flyway migrate
```

### Oracle

The production dialect. Verify against it before any release — rendering DDL is
not the same as running it.

```bash
docker compose --profile oracle up -d oracle    # large image, slow first boot
DATABASE_URL="oracle+oracledb://taskhub:taskhub@localhost:1521/?service_name=FREEPDB1" \
  ./scripts/migrate.sh
```

### What Flyway is not allowed to do

`clean` drops every object in the schema. It is never part of an automated run,
and CI asserts it is absent from the manifests. `baselineOnMigrate` is also
deliberately off by default: on a non-empty schema with no history table it
marks migrations as applied *without running them* and reports success, which
leaves you with an empty database and a green log.

To adopt Flyway on a schema that already exists, opt in explicitly:

```bash
FLYWAY_BASELINE_ON_MIGRATE=true ./scripts/migrate.sh
```

---

## Configuration

All configuration is environment variables; see [`.env.example`](../.env.example).
No secrets are committed.

| Variable | Purpose |
| -------- | ------- |
| `DATABASE_URL` | SQLAlchemy URL — the only difference between dev and prod |
| `CORS_ORIGINS` | comma-separated; empty in production, where the API serves the SPA |
| `ENABLED_SOURCES` | which inbound adapters are live |
| `ENABLED_DESTINATIONS` | which outbound adapters are live (`local` is always on) |
| `STATIC_DIR` | built SPA to serve; absent in dev, where Vite serves it |

Connection string shapes:

```
sqlite+pysqlite:///./dev.db
postgresql+psycopg://user:password@host:5432/taskhub
oracle+oracledb://user:password@host:1521/?service_name=YOUR_SERVICE
```

If a password contains `@`, `/` or `:`, percent-encode it. `app/db/jdbc.py`
decodes it again for Flyway.

To see exactly what Flyway will be handed:

```bash
cd backend && .venv/bin/python -m app.db.jdbc     # password redacted
```

---

## Jira

Optional. Leave blank and drop `jira` from `ENABLED_SOURCES` /
`ENABLED_DESTINATIONS` if unused — the Import tab will show a clear
"not configured" banner either way.

```bash
JIRA_BASE_URL=https://your-org.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=...        # id.atlassian.com/manage-profile/security/api-tokens
JIRA_PROJECT_KEY=OPS      # where pushed issues are created
JIRA_ISSUE_TYPE=Task
```

Credentials stay server-side; the browser only ever sends the targeting (an
issue key or a JQL query).

### Criticality and impact

Jira has no native concept of either. Two options:

**Map custom fields.** Find the field id from
`GET /rest/api/3/field` on your instance:

```bash
JIRA_CRITICALITY_FIELD=customfield_10042
JIRA_IMPACT_FIELD=customfield_10043
```

Values are matched case-insensitively against the canonical scales plus common
aliases (`Sev 1` → critical, `Large` → l). Anything off-scale leaves the field
blank and warns rather than guessing.

**Leave them unset**, which is the normal case. The review popup asks for them
on import, and a push records them as `taskhub-crit-*` / `taskhub-impact-*`
labels so the information survives the round trip.

### Importing

Targeted only — one issue key, or one JQL query. There is no "import
everything". A single issue opens the review **modal**; a query opens the review
**table**.

---

## Email

Nothing to configure. Drag a saved `.msg` or `.eml` onto the drop zone, or use
the file picker.

There is **no Outlook or Graph connection** — the file is parsed locally.
Dragging directly out of the Outlook desktop app is unreliable and out of
scope: Outlook exposes a virtual file the browser usually cannot read. Save the
message first, then drop or pick it.

Idempotency uses the `Message-ID` header. Messages without one (some drafts and
some Outlook saves) fall back to a hash of the file contents, and the review
screen says so — that key is only as stable as the bytes on disk.

Attachments are counted and named in `raw_payload`, not extracted.

---

## Configuring fields and defaults

The **Config** tab is the admin screen for dropdowns and import defaults. No
restart or migration is needed for anything on it.

### Fields

Builtin scales — status, priority, criticality, impact — can be **relabelled,
reordered and subset**. If your organisation says "Sev 1" rather than
"critical", rename it here and every dropdown and filter follows.

Their underlying *values* are fixed. Two things key off them:

* the watch score's weight tables (`app/services/watch.py`)
* every adapter's mapping table (`Sev 1 -> critical`, `P0 -> urgent`, …)

An invented value would score zero and map from nothing, so adding one is a
code change that also updates those. The API refuses it rather than letting it
degrade silently.

**Custom fields** — Type, Platform, whatever you need — have neither coupling
and are fully user-defined. Add one on the Config tab and it appears as a
dropdown in the review screens immediately. Values are stored per task in
`tasks.custom_fields` and validated against the configured options at commit
time. Mark one *required* and a blank value blocks commit, exactly like a blank
title.

Deleting a custom field removes its definition and its defaults, but leaves
values already written to existing tasks alone — deleting a definition should
not silently rewrite history.

### Per-flow defaults

Each import flow gets its own defaults. A typical setup:

| Flow | Why |
| ---- | --- |
| Email | Emails carry nothing but a subject and a body, so default Type=Request, Platform=Unknown, Project=<your team> |
| CSV | Usually richer, so fewer defaults are needed |
| Jira | Defaults fill only the gaps Jira has no field for |

Defaults are applied **before review** and **only where the source left the
field blank** — a source is authoritative for what it actually knows, so a
default never overwrites a real value. Every applied default is announced in
the draft's warnings, so the reviewer can see it was configuration talking
rather than the source, and can change it before committing.

`project` and `assignee` can also be defaulted even though they are free text
rather than dropdowns.

---

## Day-to-day commands

```bash
# backend
cd backend
.venv/bin/python -m pytest              # ~174 tests, no network or DB needed
.venv/bin/ruff check app tests
.venv/bin/ruff format app tests

# frontend
cd frontend
npm run build                           # tsc -b && vite build
npm run dev

# migrations
./scripts/migrate.sh info

# schema parity — after any schema change
cd backend
PARITY_DATABASE_URL="$DATABASE_URL" .venv/bin/python -m pytest tests/test_schema_parity.py
```

---

## Changing the schema

There is no autogenerate. A schema change is a deliberate, four-part edit:

1. Update the SQLAlchemy model in `backend/app/models/`.
2. Add `V<n>__description.sql` to **all three** dialect folders. Never edit an
   applied migration — Flyway validates checksums and will refuse to run.
3. Apply and verify parity:

   ```bash
   ./scripts/migrate.sh
   cd backend
   PARITY_DATABASE_URL="$DATABASE_URL" .venv/bin/python -m pytest tests/test_schema_parity.py
   ```

4. Apply against Oracle before release.

The parity test compares tables, columns, nullability, primary keys, unique
constraints and indexes. It does not compare column *types*, which legitimately
differ per dialect — that is the whole reason the SQL is maintained per dialect.

Oracle constraints that shape every schema decision are listed in
[`.github/instructions/database.instructions.md`](../.github/instructions/database.instructions.md).

---

## Deploying

```bash
docker build -t task-hub .
docker run -p 8080:8080 -e DATABASE_URL=... task-hub
```

The image serves the API *and* the built SPA from one origin, so production is
a single Deployment with no CORS configuration.

Base images are parameterised for an internal mirror:

```bash
docker build \
  --build-arg BASE_REGISTRY=registry.internal.example.com \
  --build-arg NODE_IMAGE=ubi9/nodejs-20 \
  --build-arg PYTHON_IMAGE=ubi9/python-312 \
  -t task-hub .
```

Full OpenShift instructions — arbitrary-UID constraints, the Flyway migration
Job, and both build paths — are in
[`deploy/openshift/README.md`](../deploy/openshift/README.md).

---

## Troubleshooting

| Symptom | Cause |
| ------- | ----- |
| `no such table: tasks` | Migrations not applied. Run `./scripts/migrate.sh`. |
| Flyway says "Successfully baselined" but there are no tables | `baselineOnMigrate` was on against a non-empty schema. Drop the schema and migrate again without it. |
| `Migration checksum mismatch` | An applied migration was edited. Restore it and add a new `V<n>` instead. |
| Frontend loads but every panel errors | Backend not running on 8000, or migrations not applied. Check `curl localhost:8000/api/ready`. |
| `ModuleNotFoundError: psycopg` / `oracledb` | Install the extra: `pip install -e ".[dev,postgres]"`. |
| Jira import returns 400 "not configured" | `JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` unset. |
| Jira push fails "set JIRA_PROJECT_KEY" | Pushing creates issues and needs a target project. |
| `.msg` fails to parse | Install the extra: `pip install -e ".[dev,email]"`. `.eml` needs nothing. |
| Schema parity fails after a model change | The migration SQL was not updated in all three dialect folders. |
| Pod runs but never becomes Ready | `/api/ready` is failing — the database is unreachable from the cluster. |
