---
applyTo: "frontend/src/**/*.ts,frontend/src/**/*.tsx"
---

# Frontend

React 19 + TypeScript, Vite. No state library, no CSS framework — plain
`useState`/`useEffect` and one stylesheet. Keep it that way unless there is a
concrete reason not to.

## Structure

```
api/       typed client mirroring the backend schemas — the ONLY place fetch() lives
import/    one panel per source, plus DraftReview which both share
review/     ReviewTable (many items) and ReviewModal (one)
filters/   one filter model shared by the list, calendar and watch views
tasks/ calendar/ watch/
```

`api/types.ts` mirrors `backend/app/schemas/task.py`. Change one, change the
other.

## Rules

- **Never hardcode an enum scale or a provider list.** Options come from
  `/api/enums`, `/api/providers` and `/api/tasks/facets`, so a backend change
  shows up without a frontend edit. A literal `['low','medium','high']` in a
  component is a bug.
- **Client validation mirrors the server; it does not replace it.**
  `validateDraft` exists for immediate feedback. The server re-validates
  everything.
- **Filters live in `filters/filters.ts`.** Do not add a view-local filter —
  the three views must not drift apart.
- Guard against out-of-order responses when refetching on a changing
  dependency (the `let stale = false` cleanup pattern in `TasksView`).
- FullCalendar owns all date maths. Do not hand-roll date arithmetic; pass the
  ISO strings the API already returns.
- The dropzone always ships with a file-picker fallback. Dragging out of the
  Outlook desktop app exposes a virtual file the browser usually cannot read.

## Style

- `tsc -b` is strict and `erasableSyntaxOnly` is on: no constructor parameter
  properties, no enums. Plain fields and union types.
- Components take explicit props; no prop-drilling through more than two levels
  without asking whether the shape is right.
- Prefer showing the user *why* over a bare value: "jira — default for project
  Platform" beats "jira", and the watch view shows its score breakdown.
