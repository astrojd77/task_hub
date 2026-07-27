# Task Hub — single image serving the API and the built SPA.
#
# Base images are parameterised so this builds against an internal mirror
# without editing the file:
#
#   podman build \
#     --build-arg BASE_REGISTRY=registry.internal.example.com \
#     --build-arg NODE_IMAGE=ubi9/nodejs-20 \
#     --build-arg PYTHON_IMAGE=ubi9/python-312 \
#     -t task-hub .
#
# Defaults are Red Hat UBI9, which is what most enterprise OpenShift base-image
# policies allow and what internal mirrors usually carry.
#
# Built to satisfy OpenShift's `restricted-v2` SCC, which drives the decisions
# that otherwise look odd:
#
#   * The container runs as an ARBITRARY UID chosen by OpenShift, not the UID
#     in the `USER` line. That UID is always a member of group 0, so everything
#     the app needs must be group-0 readable/writable.
#   * It must not run as root and must not need to escalate.
#   * It cannot bind a privileged port, hence 8080.
#
# UBI images already run as uid 1001 in group 0 with a writable HOME, so most
# of that is inherited rather than hand-rolled.
#
# Migrations are NOT run here — Flyway applies them from a separate Job, so
# scaling past one replica cannot race two migration runs.

ARG BASE_REGISTRY=registry.access.redhat.com
ARG NODE_IMAGE=ubi9/nodejs-20
ARG PYTHON_IMAGE=ubi9/python-312

# ----------------------------------------------------------- frontend build
FROM ${BASE_REGISTRY}/${NODE_IMAGE} AS frontend

WORKDIR /opt/app-root/src
# Manifests first so the dependency layer caches independently of source.
COPY --chown=1001:0 frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY --chown=1001:0 frontend/ ./
RUN npm run build


# ------------------------------------------------------------------ runtime
FROM ${BASE_REGISTRY}/${PYTHON_IMAGE} AS runtime

ARG APP_VERSION=0.1.0

LABEL org.opencontainers.image.title="Task Hub" \
      org.opencontainers.image.description="Import, review, commit and route work items" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.licenses="Proprietary" \
      io.openshift.expose-services="8080:http" \
      io.k8s.description="Task hub for engineering leadership"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ROOT=/opt/app-root \
    STATIC_DIR=/opt/app-root/src/static \
    PORT=8080

WORKDIR /opt/app-root/src

# Dependencies resolve from pyproject alone, so this layer survives source
# edits. The stub package keeps setuptools happy before the real source lands.
COPY --chown=1001:0 backend/pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install --no-cache-dir ".[oracle,postgres,email]" \
    && rm -rf app

COPY --chown=1001:0 backend/app ./app
# Shipped for reference and for `flyway info` against a running deployment;
# the migration Job mounts the same SQL from this image.
COPY --chown=1001:0 backend/db ./db
COPY --from=frontend --chown=1001:0 /opt/app-root/src/dist ./static

# Belt and braces: UBI already owns /opt/app-root as 1001:0, but an arbitrary
# UID only inherits access through group 0, so make that explicit.
USER 0
RUN chgrp -R 0 /opt/app-root && chmod -R g=u /opt/app-root
USER 1001

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
