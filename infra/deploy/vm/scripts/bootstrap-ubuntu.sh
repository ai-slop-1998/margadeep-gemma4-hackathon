#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash infra/deploy/vm/scripts/bootstrap-ubuntu.sh"
  exit 1
fi

apt-get update
apt-get install -y \
  build-essential \
  ca-certificates \
  curl \
  git \
  nginx \
  python3.11 \
  python3.11-dev \
  python3.11-venv \
  postgresql \
  postgresql-contrib \
  unzip

mkdir -p /opt/margadeep/kg_memory /etc/margadeep /var/log/margadeep

if [[ ! -f /etc/margadeep/margadeep.env ]]; then
  cp infra/deploy/vm/margadeep.env.example /etc/margadeep/margadeep.env
  echo "Created /etc/margadeep/margadeep.env. Edit it before starting services."
fi

cd apps/backend
python3.11 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Bootstrap complete. Next: edit /etc/margadeep/margadeep.env, initialize Postgres, then install systemd units."
