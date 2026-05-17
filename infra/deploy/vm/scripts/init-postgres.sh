#!/usr/bin/env bash
set -euo pipefail

source /etc/margadeep/margadeep.env

sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO
\$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${PGUSER}') THEN
    CREATE ROLE ${PGUSER} LOGIN PASSWORD '${PGPASSWORD}';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE ${PGDATABASE} OWNER ${PGUSER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${PGDATABASE}')\\gexec
SQL

PGPASSWORD="${PGPASSWORD}" psql \
  --host "${PGHOST}" \
  --port "${PGPORT}" \
  --username "${PGUSER}" \
  --dbname "${PGDATABASE}" \
  -f "${MARGADEEP_BACKEND_DIR}/sql/poc_personalization_schema.sql"

cd "${MARGADEEP_BACKEND_DIR}"
PYTHONPATH=. "${MARGADEEP_BACKEND_VENV}/bin/python" scripts/seed_poc_personalization.py
