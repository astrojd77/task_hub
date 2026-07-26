# Deploying Task Hub to OpenShift

One image, one Deployment, one Route. The container serves the API *and* the
built SPA from the same origin, so there is no separate frontend deployment and
no CORS configuration in production.

Requires `oc` (any 4.x) — the manifests use `labels:` with `pairs`, which needs
the kustomize built into kubectl 1.24+ / OpenShift 4.11+.

---

## Layout

```
deploy/openshift/
  base/                    everything needed to run
    configmap.yaml           non-secret config
    secret.example.yaml      reference only — NOT applied by kustomize
    deployment.yaml          the app
    service.yaml             ClusterIP :8080
    route.yaml               edge TLS, HTTP redirected
    job-migrate.yaml         alembic upgrade head, run once per release
  incluster-build/         optional: build the image inside the cluster
```

Pick **one** of the two image paths below, then follow "Deploy".

---

## Image path A — external registry (CI builds and pushes)

```bash
podman build -t quay.io/your-org/task-hub:0.1.0 .
podman push  quay.io/your-org/task-hub:0.1.0
```

Point the manifests at it by editing the `images:` block in
`base/kustomization.yaml`:

```yaml
images:
  - name: task-hub
    newName: quay.io/your-org/task-hub
    newTag: 0.1.0
```

(`kustomize edit set image` needs the standalone `kustomize` binary; `oc` and
`kubectl` embed kustomize for rendering only, not for editing.)

If the registry is private, add a pull secret to the namespace's default
service account:

```bash
oc create secret docker-registry regcred \
  --docker-server=quay.io --docker-username=... --docker-password=...
oc secrets link default regcred --for=pull
```

Apply from `deploy/openshift/base`.

## Image path B — in-cluster build (no external registry)

For environments where pushing from CI is not an option. The whole build,
including the Node frontend stage, runs in the cluster — no local Docker or
Node needed.

```bash
oc apply -k deploy/openshift/incluster-build
oc start-build task-hub --from-dir=. --follow     # from the repo root
```

`--from-dir=.` uploads the working tree as the build context, honouring
`.dockerignore`. The overlay also wires an ImageStream trigger, so a finished
build rolls the Deployment automatically.

Apply from `deploy/openshift/incluster-build`.

---

## Deploy

```bash
oc new-project task-hub          # or: oc project <existing>

# 1. Credentials. Created out of band on purpose — the Secret is not part of
#    the kustomization, so a placeholder connection string cannot reach a
#    real cluster via `oc apply -k`.
oc create secret generic task-hub-secret \
  --from-literal=DATABASE_URL='oracle+oracledb://USER:PASSWORD@HOST:1521/?service_name=YOUR_SERVICE'

# 2. Everything else. Use whichever directory matches your image path.
oc apply -k deploy/openshift/base

# 3. Migrate. The Job is in the kustomization, so step 2 already started it.
oc wait --for=condition=complete job/task-hub-migrate --timeout=300s
oc logs job/task-hub-migrate

# 4. Check it came up.
oc rollout status deployment/task-hub
oc get route task-hub -o jsonpath='{.spec.host}{"\n"}'
```

### Upgrading

```bash
# Jobs are immutable — delete before re-applying, or the apply fails.
oc delete job/task-hub-migrate --ignore-not-found
oc apply -k deploy/openshift/base
oc wait --for=condition=complete job/task-hub-migrate --timeout=300s
oc rollout status deployment/task-hub
```

Migrations run as a **separate Job, not an initContainer**, because every
replica runs its own initContainers — two replicas would race two
`alembic upgrade head` runs against the same database.

---

## Why the image looks the way it does

OpenShift's default `restricted-v2` SCC runs the container as an **arbitrary
UID** picked from the namespace's range, not as the UID in the `USER` line.
That UID is always in group 0. Three consequences, all handled in the
`Dockerfile`:

| Constraint | Handling |
| ---------- | -------- |
| Arbitrary UID, always in group 0 | `chgrp -R 0 /app && chmod -R g=u /app` |
| That UID has no home directory | `HOME=/app`, which is group-writable |
| Cannot bind a privileged port | listens on 8080 |

The manifests deliberately set **no** `runAsUser` and no `fsGroup` — hardcoding
either is the usual reason an image fails under `restricted-v2`. The pod does
declare `runAsNonRoot`, `allowPrivilegeEscalation: false`, `drop: ["ALL"]` and
the `RuntimeDefault` seccomp profile, which is the compliant set.

Verified locally with:

```bash
docker run --user 1000670000:0 -e DATABASE_URL=... task-hub:latest
```

### Optional hardening

`readOnlyRootFilesystem: true` also works — the app writes nothing to disk —
but needs an `emptyDir` mounted at `/tmp`. Left off by default so a first
deploy cannot fail on a surprise temp-file write.

---

## Probes

| Probe | Path | Why |
| ----- | ---- | --- |
| startup | `/api/health` | 90s of grace. An Oracle connection over a corporate network can be slow, and without this the liveness probe would kill the pod before it finished starting. |
| liveness | `/api/health` | Process check only — no database call, so a database blip cannot trigger a restart loop. |
| readiness | `/api/ready` | Runs `SELECT 1`. A pod that cannot reach the database leaves the Service's endpoints instead of being restarted. |

`/api/ready` uses `select(literal(1))` rather than `text("SELECT 1")` so
SQLAlchemy renders the `FROM DUAL` that Oracle requires.

---

## Database

`DATABASE_URL` is the only thing that differs between dev and prod.
`python-oracledb` runs in **thin mode**, so the image needs no Oracle Instant
Client and no `LD_LIBRARY_PATH`.

```
oracle+oracledb://USER:PASSWORD@HOST:1521/?service_name=YOUR_SERVICE
postgresql+psycopg://USER:PASSWORD@HOST:5432/taskhub
```

Both drivers are baked into the image (`pip install ".[oracle,postgres]"`).

Before the first production deploy, apply the migrations against a real Oracle
instance — rendering the DDL is not the same as running it:

```bash
# renders without a database, catches type/identifier problems
DATABASE_URL="oracle+oracledb://u:p@h:1521/?service_name=X" alembic upgrade head --sql

# the real thing
docker compose --profile oracle up -d oracle
DATABASE_URL="oracle+oracledb://taskhub:taskhub@localhost:1521/?service_name=FREEPDB1" \
  backend/.venv/bin/alembic upgrade head
```

If the Oracle host is outside the cluster, confirm egress on 1521 is allowed
before blaming the app — a blocked connection shows up as a pod that stays
Running but never becomes Ready, with `/api/ready` returning 503.

---

## Troubleshooting

| Symptom | Likely cause |
| ------- | ------------ |
| Pod `CrashLoopBackOff`, logs show a permission error | Something in the image is not group-0 writable. Check the `chgrp`/`chmod` layer survived an edit to the Dockerfile. |
| Pod Running but never Ready | `/api/ready` is failing — the database is unreachable. `oc logs deployment/task-hub` and check egress to port 1521. |
| `oc apply` fails on the Job | Jobs are immutable. `oc delete job/task-hub-migrate` first. |
| Route 503 | No Ready endpoints behind the Service; see above. |
| Route times out on a big CSV | Raise `haproxy.router.openshift.io/timeout` on the Route (120s by default here). |
| Build fails in the Node stage | `--from-dir=.` respects `.dockerignore`; make sure `frontend/package-lock.json` is committed. |

Useful:

```bash
oc logs -f deployment/task-hub
oc logs job/task-hub-migrate
oc describe pod -l app.kubernetes.io/name=task-hub
oc rsh deployment/task-hub id        # confirm the assigned UID and group 0
```
