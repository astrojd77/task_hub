---
applyTo: "deploy/**,Dockerfile,docker-compose.yml,scripts/**"
---

# Deployment

Target is **OpenShift**. One image serves the API and the built SPA from a
single origin: one Deployment, one Service, one Route, no CORS in production.

## The arbitrary-UID rule

OpenShift's `restricted-v2` SCC runs the container as a **UID assigned from the
namespace range**, not the UID in the `USER` line. That UID is always a member
of group 0. Everything follows from this:

- Never set `runAsUser` or `fsGroup` in a manifest. Hardcoding either is the
  usual reason an image fails under `restricted-v2` — OpenShift assigns them.
- Files the app needs must be group-0 owned and group-writable
  (`chgrp -R 0 … && chmod -R g=u …`).
- `HOME` must point somewhere writable; an assigned UID has no home directory.
- Listen on 8080. A non-root process cannot bind a privileged port.
- Keep `runAsNonRoot: true`, `allowPrivilegeEscalation: false`,
  `capabilities: drop: [ALL]`, `seccompProfile: RuntimeDefault`.

Verify locally before claiming it works:

```bash
docker run --user 1000670000:0 -e DATABASE_URL=... task-hub
```

## Base images

Parameterised via build args so the build points at an internal mirror without
editing the Dockerfile:

```bash
podman build \
  --build-arg BASE_REGISTRY=registry.internal.example.com \
  --build-arg NODE_IMAGE=ubi9/nodejs-20 \
  --build-arg PYTHON_IMAGE=ubi9/python-312 \
  -t task-hub .
```

Do not reintroduce a hardcoded Docker Hub base image.

## Migrations

Flyway, as a **separate Job** — never an initContainer on the Deployment, since
every replica runs its own initContainers and two replicas would race two
migration runs against one database.

The Job's init container pulls the SQL out of the *application image*, so the
migrations applied are always the ones that shipped with the code being
deployed. It derives the JDBC URL, credentials and dialect folder from the same
`DATABASE_URL` the app uses, via `app/db/jdbc.py`.

Credentials are rendered to a file on a memory-backed `emptyDir`, not passed in
argv where they would show up in the process list.

## Manifests

- kustomize `labels` with `includeSelectors: false` — the deprecated
  `commonLabels` folds labels into a Deployment's **immutable** selector.
- The Secret stays out of the kustomization on purpose, so a placeholder
  connection string cannot reach a cluster via `oc apply -k`.
- Split probes: liveness on `/api/health` (process only, so a database blip
  cannot cause a restart loop), readiness on `/api/ready` (runs `SELECT 1`),
  plus a startup probe for slow Oracle connections.
- Pin image tags. `latest` in a migration Job is not reproducible.
