#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash infra/deploy/vm/scripts/bootstrap-vllm.sh"
  exit 1
fi

apt-get update
apt-get install -y python3.11 python3.11-dev python3.11-venv build-essential

python3.11 -m venv /opt/margadeep/vllm
. /opt/margadeep/vllm/bin/activate
pip install --upgrade pip
pip install vllm

echo "vLLM installed under /opt/margadeep/vllm. Configure VLLM_MODEL in /etc/margadeep/margadeep.env before starting margadeep-vllm."
