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
    job-migrate.yaml         Flyway migrate, run once per release
  incluster-build/         optional: build the image inside the cluster
```

Pick **one** of the two image paths below, then follow "Deploy".

---

## Image path A — external registry (CI builds and pushes)

```bash
podman build \
  --build-arg BASE_REGISTRY=registry.internal.example.com \
  --build-arg NODE_IMAGE=ubi9/nodejs-20 \
  --build-arg PYTHON_IMAGE=ubi9/python-312 \
  -t quay.io/your-org/task-hub:0.1.0 .
podman push quay.io/your-org/task-hub:0.1.0
```

Base images default to Red Hat UBI9 and are parameterised, so pointing the
build at an internal mirror needs no edit to the Dockerfile.

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

### How migrations work

Flyway applies them from a **separate Job, not an initContainer on the
Deployment** — every replica runs its own initContainers, so two replicas would
race two migration runs against one database.

The Job has two steps:

1. An **init container running the application image** copies the SQL for the
   right dialect out of that image and renders a `flyway.conf`. Taking the SQL
   from the image rather than a ConfigMap guarantees the migrations applied are
   the ones that shipped with the code being deployed — a ConfigMap can drift,
   this cannot. Dialect, JDBC URL and credentials all come from the same
   `DATABASE_URL` the app uses, via `app/db/jdbc.py`.
2. The **Flyway container** runs `migrate` against that config.

Credentials are written to a file on a memory-backed `emptyDir` rather than
passed in argv, where they would appear in the process list, and never touch a
node's disk.

The Job runs `migrate` only. `clean` drops every object in the schema, and CI
asserts it never appears in these manifests.

Point the `flyway` image at your mirror in `base/kustomization.yaml`:

```yaml
images:
  - name: flyway
    newName: registry.internal.example.com/flyway/flyway
    newTag: 11-alpine
```

Adding a migration means adding `V<n>__*.sql` to
`backend/db/migration/{postgresql,oracle,sqlite}/` — never editing an applied
one, since Flyway validates checksums.

---

## Why the image looks the way it does

OpenShift's default `restricted-v2` SCC runs the container as an **arbitrary
UID** picked from the namespace's range, not as the UID in the `USER` line.
That UID is always in group 0. Three consequences, all handled in the
`Dockerfile`:

| Constraint | Handling |
| ---------- | -------- |
| Arbitrary UID, always in group 0 | `chgrp -R 0 /opt/app-root && chmod -R g=u /opt/app-root` |
| That UID has no home directory | UBI already sets a writable `HOME` under `/opt/app-root` |
| Cannot bind a privileged port | listens on 8080 |

Base images default to Red Hat UBI9, which already runs as uid 1001 in group 0
with a writable home, so most of this is inherited rather than hand-rolled.
They are parameterised via `BASE_REGISTRY` / `NODE_IMAGE` / `PYTHON_IMAGE`
build args for an internal mirror.

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
docker compose --profile oracle up -d oracle
DATABASE_URL="oracle+oracledb://taskhub:taskhub@localhost:1521/?service_name=FREEPDB1" \
  ./scripts/migrate.sh

# then confirm the SQL still matches the models
cd backend
PARITY_DATABASE_URL="oracle+oracledb://taskhub:taskhub@localhost:1521/?service_name=FREEPDB1" \
  .venv/bin/python -m pytest tests/test_schema_parity.py
```

If the Oracle host is outside the cluster, confirm egress on 1521 is allowed
before blaming the app — a blocked connection shows up as a pod that stays
Running but never becomes Ready, with `/api/ready` returning 503.

---

## Troubleshooting

| Symptom | Likely cause |
| ------- | ------------ |
| Migration Job reports "Successfully baselined" but tables are missing | `baselineOnMigrate` ran against a non-empty schema and marked migrations applied without running them. |
| `Migration checksum mismatch` | An applied migration was edited. Restore it and add a new `V<n>`. |
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
