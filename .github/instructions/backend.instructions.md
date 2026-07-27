---
applyTo: "backend/app/**/*.py"
---

# Backend

FastAPI + SQLAlchemy 2.x (`Mapped` / `mapped_column`) + Pydantic v2.

## Layering

```
api/         routers — thin. Parse, delegate, translate errors to status codes.
services/    the logic. commit.py is the ONLY writer to the task store.
providers/   adapters. Own their platform's vocabulary; never touch the DB.
models/      SQLAlchemy. Portable across SQLite / Postgres / Oracle.
schemas/     Pydantic. DraftTask (permissive) -> TaskCommitIn (strict) -> TaskOut.
core/        config and the canonical enums.
```

A router must not contain business logic, and a service must not know about
`HTTPException`. Services raise domain errors (`ProviderError`, `RoutingError`)
and the router maps them:

- adapter/user-fixable problem → 400 with the message verbatim
- unknown or disabled provider → 404
- conflicts with where a task came from → 409
- schema violation → 422 (Pydantic does this for free)
- database unreachable → 503, **type name only**, never the driver message,
  which carries host, user and DSN

## Draft vs commit

`DraftTask` is deliberately lax — an email with no subject or a CSV row with a
junk priority must survive parsing so the user can *see* and fix it.
`TaskCommitIn` is where rules bite. Do not move validation earlier; the review
step is the product.

`DraftTask` sets `validate_assignment=True` because drafts get mutated after
construction (`services/drafts.py`). Assigning a raw string to an enum field
would otherwise slip through.

## Providers

```python
class SourceProvider(Protocol):
    id: str
    display_name: str
    def config_schema(self) -> dict: ...
    def fetch(self, config) -> list[RawItem]: ...      # no DB session, ever
    def to_draft(self, raw: RawItem) -> DraftTask: ...  # sets source_ref
```

- Inject the platform client through `__init__` so tests never touch the
  network. Every adapter test uses a fake client.
- Optional `describe(config) -> dict` feeds `DraftBatch.meta` — that is how an
  adapter says whether its batch wants the modal or the table.
- Unmappable value → leave the field blank **and** append a warning. Three
  distinct cases deserve three distinct messages: not configured, configured
  but empty, and configured but off-scale.

## Tests

`pytest`, no network, no live database. In-memory SQLite via the `db` fixture;
`client` gives a `TestClient` with `get_db` overridden.

Test behaviour and the reason it matters. Where a test encodes a decision, say
so in the docstring — e.g. why a row hash covers the original row rather than
the reviewed one.
