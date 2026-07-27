#!/usr/bin/env bash
#
# Run Flyway against whatever DATABASE_URL points at.
#
#   ./scripts/migrate.sh              # migrate
#   ./scripts/migrate.sh info         # what's applied
#   ./scripts/migrate.sh validate     # checksums still match?
#   ./scripts/migrate.sh clean        # drop everything (dev only, prompts)
#
# Dev convenience only — production migrates via the OpenShift Job in
# deploy/openshift/base/job-migrate.yaml, which runs the same Flyway image
# against the same SQL.
#
# The dialect, JDBC URL and credentials are all derived from DATABASE_URL by
# app/db/jdbc.py, so there is exactly one place to configure a database.

set -euo pipefail

COMMAND="${1:-migrate}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLYWAY_IMAGE="${FLYWAY_IMAGE:-flyway/flyway:11-alpine}"

PYTHON="${REPO_ROOT}/backend/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3)"
fi

# Load .env if present so this matches how the app is configured.
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

: "${DATABASE_URL:=sqlite+pysqlite:///./dev.db}"
export DATABASE_URL

cd "${REPO_ROOT}/backend"

field() { "${PYTHON}" -m app.db.jdbc "${DATABASE_URL}" --field "$1"; }

JDBC_URL="$(field url)"
DB_USER="$(field user)"
DB_PASSWORD="$(field password)"
MIGRATION_DIR="$(field migration_dir)"

echo "flyway ${COMMAND}"
echo "  dialect : ${MIGRATION_DIR}"
echo "  url     : ${JDBC_URL}"
echo "  sql     : backend/db/migration/${MIGRATION_DIR}"

DOCKER_ARGS=(
  --rm
  --network host
  -v "${REPO_ROOT}/backend/db/migration/${MIGRATION_DIR}:/flyway/sql:ro"
  -e "FLYWAY_URL=${JDBC_URL}"
  -e "FLYWAY_USER=${DB_USER}"
  -e "FLYWAY_PASSWORD=${DB_PASSWORD}"
  -e "FLYWAY_CONNECT_RETRIES=10"
)

# Deliberately NOT setting baselineOnMigrate. On a non-empty schema with no
# history table, Flyway would mark V1 as already applied *without running it*
# and report success — so a fresh database would silently come up with no
# tables. Adopting Flyway on a pre-existing schema is a conscious act:
#   FLYWAY_BASELINE_ON_MIGRATE=true ./scripts/migrate.sh
if [[ -n "${FLYWAY_BASELINE_ON_MIGRATE:-}" ]]; then
  DOCKER_ARGS+=(-e "FLYWAY_BASELINE_ON_MIGRATE=${FLYWAY_BASELINE_ON_MIGRATE}")
fi

# SQLite has no server, so the database file has to be visible inside the
# container and the JDBC path rewritten to where it is mounted.
if [[ "${MIGRATION_DIR}" == "sqlite" ]]; then
  DB_PATH="${JDBC_URL#jdbc:sqlite:}"
  DB_DIR="$(cd "$(dirname "${REPO_ROOT}/backend/${DB_PATH#./}")" && pwd)"
  DB_FILE="$(basename "${DB_PATH}")"
  touch "${DB_DIR}/${DB_FILE}"
  DOCKER_ARGS+=(
    -v "${DB_DIR}:/flyway/db"
    -e "FLYWAY_URL=jdbc:sqlite:/flyway/db/${DB_FILE}"
  )
fi

exec docker run "${DOCKER_ARGS[@]}" "${FLYWAY_IMAGE}" "${COMMAND}"
