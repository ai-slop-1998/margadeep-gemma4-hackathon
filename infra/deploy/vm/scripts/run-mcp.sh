#!/usr/bin/env bash
set -euo pipefail

source /etc/margadeep/margadeep.env

mkdir -p "${MARGADEEP_KG_MEMORY_DIR}" "${MARGADEEP_LOG_DIR}"
cd "${MARGADEEP_BACKEND_DIR}"

exec "${MARGADEEP_BACKEND_VENV}/bin/python" \
  app/mcp_server/cli.py \
  --http-stateless \
  --host 127.0.0.1 \
  --port 8001
