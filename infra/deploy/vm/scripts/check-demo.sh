#!/usr/bin/env bash
set -euo pipefail

base_url="${1:-http://127.0.0.1:8090}"

echo "BFF health:"
curl -fsS "${base_url}/health"
echo

echo "MCP health:"
curl -fsS "http://127.0.0.1:8001/api/v1/health"
echo

echo "vLLM models, if enabled:"
curl -fsS "http://127.0.0.1:8000/v1/models" || true
echo
