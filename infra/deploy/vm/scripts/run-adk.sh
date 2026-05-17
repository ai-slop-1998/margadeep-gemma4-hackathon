#!/usr/bin/env bash
set -euo pipefail

source /etc/margadeep/margadeep.env

cd "${MARGADEEP_BACKEND_DIR}"

exec "${MARGADEEP_BACKEND_VENV}/bin/adk" web \
  --host 127.0.0.1 \
  --port 8082 \
  ./app/agents
