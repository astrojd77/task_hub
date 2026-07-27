# Copilot instructions — Task Hub

Repository-wide context for GitHub Copilot (chat, completions and code review).
Path-specific rules live in `.github/instructions/`.

## What this is

A task/project management hub for engineering leadership. It imports work items
from targeted sources, holds them as **drafts for review**, commits reviewed
tasks to a canonical store, shows a unified calendar, and routes each task to a
selectable destination platform.

Backend: FastAPI + SQLAlchemy 2.x + Pydantic v2, Python 3.11+.
Frontend: React + TypeScript (Vite), FullCalendar.
Database: SQLite/Postgres in dev, **Oracle in prod**. Migrations are Flyway SQL.

## Two invariants — do not violate these

**1. Nothing is created without review.**
Every source produces *draft* tasks. `POST /api/commit` is the only code path
that writes to the task store. A source that writes to the database directly is
a bug, not an optimisation. `SourceProvider` implementations must be free of
any database session.

**2. Sources and destinations are pluggable adapters.**
Core knows about zero specific platforms. Adding a platform means writing one
adapter under `backend/app/providers/{sources,destinations}/`, registering it
with `@source` / `@destination`, and importing it in `providers/__init__.py`.

If a change to a source or destination forces an edit to the calendar, the task
list, the watch view or the commit service, the abstraction is wrong — fix the
abstraction rather than threading a special case through core.

## The canonical model

One `Task`. Three **independent** prioritization axes that must never be
collapsed into one another or into a single score at the model layer:

| Field | Question | Scale |
| ----- | -------- | ----- |
| `priority` | Urgency — what do I do first? | low, medium, high, urgent |
| `criticality` | Severity — how bad if it fails or slips? | low, medium, high, critical |
| `impact_size` | Blast radius — how much is affected? | xs, s, m, l, xl |

Sources usually supply at most `priority`. `criticality` and `impact_size` are
what the review popup exists to capture. Leaving them blank with a warning is
correct; guessing a value is not.

Enum translation is **per adapter**. Platform-native values (`Sev 1`, `P0`,
`In Progress`, Jira status categories) must never leak past the adapter that
owns them.

## Rules that are easy to get wrong

- **Idempotency** is `(source_provider, source_ref)`. CSV uses a hash of the
  *original* row — never the reviewed values, or editing then re-importing
  would duplicate. Jira uses the issue key, email the `Message-ID`.
- **Validation is server-authoritative.** The UI must never be the only gate.
  Blank summary and off-scale enums are 422s; missing due date or criticality are
  warnings returned alongside the committed tasks.
- **Never let a task loop back into the system it came from** as a *new* item
  (`app/services/routing.py:check_push_allowed`). Updating the original is fine.
- **`local` is always an available destination**, even when config omits it,
  or a commit would have nowhere to go.
- **Configurable fields.** Builtin scales (status, priority, criticality,
  impact_size) may be relabelled, reordered and subset, but a *new value* must
  never be addable: the watch weights and every adapter's mapping table key off
  those values. Custom fields have no such coupling and are fully user-defined.
- **Mapping is an override, never a replacement.** `services/source_mapping.py`
  resolves which input feeds a field and how its values translate; an adapter's
  built-in aliases and value tables still fill every gap, so an unconfigured
  install imports sensibly. Precedence is request mapping > saved mapping >
  adapter detection. An unmappable value is reported *structurally*
  (`DraftTask.unmapped`) as well as in prose, so the review screen can offer a
  one-click rule; `add_value_rule` merges rather than replacing, or teaching a
  value would wipe the input column.
- **Per-source defaults fill blanks only.** A default must never overwrite a
  value the source actually supplied, and every applied default is announced on
  the draft so the reviewer knows it was configuration talking.
- **Oracle portability** governs every schema decision — see
  `.github/instructions/database.instructions.md`.
- **Do not add heavy dependencies** or change the DB/ORM/auth approach without
  asking first.

## Conventions

- Comments explain *why*, not what. Do not narrate the code.
- Tests are named as behaviour, not as method-under-test:
  `test_reimport_updates_and_does_not_duplicate`, not `test_commit_2`.
- All timestamps are naive UTC.
- Errors the user can act on (bad file, bad mapping, bad credentials) surface
  their message verbatim as a 4xx. Never a 500.
- Secrets come from env config server-side and are never sent to or from the
  browser. `/api/health` reports the dialect, never the connection string.
- Backend: ruff, 100 columns. Frontend: the repo's tsconfig is strict; no
  `any`, no non-null assertions without a reason in a comment.

## Commands

```bash
cd backend && .venv/bin/python -m pytest       # 240 tests, no network needed
cd backend && .venv/bin/ruff check app tests
cd frontend && npm run build                   # tsc -b && vite build
./scripts/migrate.sh                           # Flyway, dialect from DATABASE_URL
```
