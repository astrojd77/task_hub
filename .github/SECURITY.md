# Security

## Reporting

Report vulnerabilities privately through GitHub's **Security → Report a
vulnerability** on this repository. Please do not open a public issue.

## What this application handles

Task Hub imports work items from CSV files, Jira and saved email messages. That
means it processes **untrusted input** — a `.msg` file or a CSV can come from
anywhere — and holds credentials for the platforms it talks to.

## Design decisions worth knowing when reviewing

**Credentials never reach the browser.** Jira credentials live in server-side
config. The client sends only the *targeting* (an issue key or a JQL query).
`/api/health` reports the database dialect, never the connection string, and
`/api/ready` returns only an exception type on failure because a driver message
carries the host, user and DSN.

**Uploads are bounded.** `MAX_UPLOAD_BYTES` (16 MB) caps request bodies and the
CSV adapter caps row count. Both are memory-pressure guards.

**Email parsing is local.** There is no Outlook or Graph connection; nothing
contacts a mail server. HTML bodies are stripped of `<script>` and `<style>`
before the text reaches the review screen, and the result is rendered as text,
never as HTML.

**The SPA fallback cannot escape its root.** `app/static.py` resolves the
requested path and checks it is still inside the static directory before
serving a file.

**Attachments are not extracted.** Only a count and filenames are recorded, so
no attachment content is written to disk.

**Migrations cannot destroy data.** The Flyway Job runs `migrate` only —
`clean` drops every object in the schema and is asserted against in CI.

## Deployment

Pods run under OpenShift's `restricted-v2` SCC: non-root, an assigned UID, no
privilege escalation, all capabilities dropped. Secrets are created out of band
rather than applied from the repository, so a placeholder connection string
cannot reach a cluster via `oc apply -k`.

There is **no authentication or authorisation in the application itself** —
it is a single-user tool and expects to sit behind whatever the platform
provides. Do not expose it publicly without putting an authenticating proxy in
front of it.
