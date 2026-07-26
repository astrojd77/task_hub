# Task Hub — single image serving the API and the built SPA.
#
# Built to satisfy OpenShift's `restricted-v2` SCC, which is the constraint
# that drives most of the odd-looking decisions here:
#
#   * The container runs as an ARBITRARY UID chosen by OpenShift, not as the
#     UID in the `USER` line. That UID is always a member of group 0, so
#     everything the app needs must be group-0 readable/writable.
#   * It must not run as root and must not need to escalate.
#   * It cannot bind a privileged port, hence 8080 rather than 80.
#
# The image also runs unchanged on plain Docker/Podman, where `USER 1001`
# applies literally.

# ----------------------------------------------------------- frontend build
FROM docker.io/library/node:22-alpine AS frontend

WORKDIR /build
# Copy manifests first so the dependency layer caches independently of source.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ------------------------------------------------------------------ runtime
FROM docker.io/library/python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # An arbitrary UID has no home directory of its own; point HOME at a path
    # that is group-0 writable so anything expecting one does not fail.
    HOME=/app \
    STATIC_DIR=/app/static

WORKDIR /app

# Dependencies resolve from pyproject alone, so this layer survives source edits.
COPY backend/pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install --no-cache-dir ".[oracle,postgres]" \
    && rm -rf app

COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY --from=frontend /build/dist ./static

# Group 0 ownership with group permissions mirroring user permissions is what
# makes the image work under an arbitrary UID.
RUN chgrp -R 0 /app && chmod -R g=u /app

EXPOSE 8080
USER 1001

# Migrations are NOT run here — they are a separate Job, so that scaling to
# more than one replica cannot race two `alembic upgrade head` runs.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
