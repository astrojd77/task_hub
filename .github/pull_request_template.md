## What and why

<!-- What changes, and the problem it solves. Link the issue if there is one. -->

## How to verify

<!-- The steps a reviewer should actually run. "Tests pass" is not enough for
     anything user-visible. -->

## Checklist

- [ ] `cd backend && .venv/bin/python -m pytest` passes
- [ ] `cd backend && .venv/bin/ruff check app tests` clean
- [ ] `cd frontend && npm run build` passes
- [ ] No secrets committed; `.env.example` updated if config changed

### If the schema changed

- [ ] A new `V<n>__*.sql` added to **all three** dialect folders
      (`postgresql`, `oracle`, `sqlite`) — there is no autogenerate
- [ ] No existing migration edited (Flyway validates checksums)
- [ ] Schema parity checked:
      `PARITY_DATABASE_URL=… pytest tests/test_schema_parity.py`
- [ ] Applied against a real Oracle instance, not just rendered

### If an adapter was added or changed

- [ ] Core untouched — the calendar, task list, watch view and commit service
      needed no edits
- [ ] Enum translation stays inside the adapter; no native values reach core
- [ ] Unmappable values leave the field blank **and** warn, rather than guessing
- [ ] Tests use a fake client; nothing hits the network

### If deployment changed

- [ ] Image verified under an arbitrary UID:
      `docker run --user 1000670000:0 …`
- [ ] No `runAsUser` or `fsGroup` added to any manifest
- [ ] `kubectl kustomize deploy/openshift/base` still renders
