#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash infra/deploy/vm/scripts/install-systemd.sh"
  exit 1
fi

install -m 0755 infra/deploy/vm/scripts/run-mcp.sh /usr/local/bin/margadeep-run-mcp
install -m 0755 infra/deploy/vm/scripts/run-adk.sh /usr/local/bin/margadeep-run-adk
install -m 0755 infra/deploy/vm/scripts/run-bff.sh /usr/local/bin/margadeep-run-bff
install -m 0755 infra/deploy/vm/scripts/run-vllm.sh /usr/local/bin/margadeep-run-vllm

install -m 0644 infra/deploy/vm/systemd/margadeep-mcp.service /etc/systemd/system/margadeep-mcp.service
install -m 0644 infra/deploy/vm/systemd/margadeep-adk.service /etc/systemd/system/margadeep-adk.service
install -m 0644 infra/deploy/vm/systemd/margadeep-bff.service /etc/systemd/system/margadeep-bff.service
install -m 0644 infra/deploy/vm/systemd/margadeep-vllm.service /etc/systemd/system/margadeep-vllm.service

systemctl daemon-reload
systemctl enable margadeep-mcp margadeep-adk margadeep-bff

echo "Installed services. Optional local model: sudo systemctl enable margadeep-vllm"
