# Margadeep VM Demo Deploy

This is the fastest live-demo path for the Android app: run the current local
backend stack on one GCP Compute Engine VM and expose only API gateway over HTTP/S.

## Runtime Shape

```text
Android app
  -> https://demo-host
      -> nginx
      -> API gateway on 127.0.0.1:8090
          -> ADK offline_prep on 127.0.0.1:8082
              -> MCP on 127.0.0.1:8001
                  -> local Postgres + pgvector profile/episode memory
                  -> local AutoSchemaKG graph files under /opt/margadeep/kg_memory
          -> online / reflect API gateway routes
```

Optional local model:

```text
ADK + AutoSchemaKG -> LiteLLM/OpenAI-compatible -> vLLM on 127.0.0.1:8000
```

## GCP VM

For a Vertex-backed demo, a normal CPU VM is enough. For local vLLM with Gemma,
use an L4 GPU VM when quota is available, or a V100 VM as the current free-credit fallback.

Suggested demo sizes:

- CPU/Vertex mode: `e2-standard-4` or `e2-standard-8`
- Local vLLM mode: `g2-standard-8` with one NVIDIA L4, or V100 for the free-credit fallback, 100GB+ boot disk

Open only ports `80` and `443` to the public internet. Keep `8001`, `8082`,
`8090`, `5432`, and `8000` bound to localhost.

## Install

On the VM:

```bash
sudo mkdir -p /opt/margadeep
sudo chown "$USER":"$USER" /opt/margadeep
git clone <repo-url> /opt/margadeep/app
cd /opt/margadeep/app

sudo bash infra/deploy/vm/scripts/bootstrap-ubuntu.sh
sudo editor /etc/margadeep/margadeep.env
```

Install `pgvector` for the VM's PostgreSQL version before initializing the DB.
Then run:

```bash
sudo bash infra/deploy/vm/scripts/init-postgres.sh
sudo bash infra/deploy/vm/scripts/install-systemd.sh
sudo systemctl start margadeep-mcp margadeep-adk margadeep-bff
```

Install nginx config:

```bash
sudo cp infra/deploy/vm/nginx/margadeep.conf /etc/nginx/sites-available/margadeep.conf
sudo ln -sf /etc/nginx/sites-available/margadeep.conf /etc/nginx/sites-enabled/margadeep.conf
sudo nginx -t
sudo systemctl reload nginx
```

Check:

```bash
bash infra/deploy/vm/scripts/check-demo.sh http://127.0.0.1:8090
curl http://YOUR_VM_IP/health
```

## Local vLLM / Gemma Mode

Install GPU drivers using the normal GCP GPU driver flow for the VM image, then:

```bash
cd /opt/margadeep/app
sudo bash infra/deploy/vm/scripts/bootstrap-vllm.sh
sudo editor /etc/margadeep/margadeep.env
sudo systemctl enable --now margadeep-vllm
curl http://127.0.0.1:8000/v1/models
```

Enable these in `/etc/margadeep/margadeep.env`:

```bash
GEMMA4_ADK_MODEL_PROVIDER=litellm
GEMMA4_LITELLM_MODEL=openai/openapi
OPENAI_API_BASE=http://127.0.0.1:8000/v1
OPENAI_API_KEY=local-vllm

RESEARCH_WEAK_MODEL=openapi
RESEARCH_CRITIC_MODEL=openapi
RESEARCH_PLANNER_MODEL=openapi
OFFLINE_SUPPORT_CLARIFIER_MODEL=openapi
GEMMA4_ONLINE_SUPPORT_MODEL=openapi

GEMMA4_KG_LLM_PROVIDER=vllm
GEMMA4_KG_LLM_MODEL=openapi
GEMMA4_KG_OPENAI_BASE_URL=http://127.0.0.1:8000/v1
GEMMA4_KG_OPENAI_API_KEY=local-vllm
```

Then restart:

```bash
sudo systemctl restart margadeep-vllm margadeep-mcp margadeep-adk margadeep-bff
```

The exact `VLLM_MODEL` / model id depends on the gated/available Gemma artifact
you use. Keep the vLLM `--served-model-name` aligned with the model names above.

### Gemma 4 E2B / MTP Container

The repo also includes an imported Gemma 4 vLLM custom-container path under
`infra/deploy/gemma4-serving/e2b-mtp`. It is intended for `1 x NVIDIA_L4` or a conservative single V100 VM and
serves `google/gemma-4-E2B-it` through the OpenAI-compatible vLLM API.

Build the image on a GPU VM or with Cloud Build:

```bash
cd /opt/margadeep/app/infra/deploy/gemma4-serving/e2b-mtp
BUILD_LOCAL=1 IMAGE_URI=gemma-e2b-mtp-vllm:local ./run_vm.sh
docker rm -f gemma-e2b-mtp
```

Then enable container-backed serving through the existing systemd service:

```bash
sudo editor /etc/margadeep/margadeep.env
```

Use these settings:

```bash
GEMMA4_ADK_MODEL_PROVIDER=litellm
GEMMA4_LITELLM_MODEL=openai/openapi
OPENAI_API_BASE=http://127.0.0.1:8000/v1
OPENAI_API_KEY=local-vllm

RESEARCH_WEAK_MODEL=openapi
RESEARCH_CRITIC_MODEL=openapi
RESEARCH_PLANNER_MODEL=openapi
OFFLINE_SUPPORT_CLARIFIER_MODEL=openapi
GEMMA4_ONLINE_SUPPORT_MODEL=openapi

VLLM_SERVING_MODE=container
VLLM_CONTAINER_IMAGE_URI=gemma-e2b-mtp-vllm:local
VLLM_MODEL=google/gemma-4-E2B-it
VLLM_SERVED_MODEL_NAME=openapi
VLLM_TENSOR_PARALLEL_SIZE=1
VLLM_ENABLE_MTP=1
VLLM_SPECULATIVE_ASSISTANT_MODEL=google/gemma-4-E2B-it-assistant
VLLM_SPECULATIVE_NUM_TOKENS=4
VLLM_MAX_MODEL_LEN=8192
VLLM_GPU_MEMORY_UTILIZATION=0.90
VLLM_GPU_DEVICES=device=0
```

If the Hugging Face model requires gated access, set either `HF_TOKEN` or
`HF_TOKEN_SECRET_RESOURCE` in `/etc/margadeep/margadeep.env`.

Start it:

```bash
sudo systemctl restart margadeep-vllm margadeep-mcp margadeep-adk margadeep-bff
curl http://127.0.0.1:8000/v1/models
```

The container remains private on `127.0.0.1:8000`; only nginx/BFF should be
public.

## Android Build

Build the Flutter Android app against the public nginx URL:

```bash
cd /opt/margadeep/app/apps/mobile_flutter
flutter build apk --release \
  --dart-define=GEMMA4_BFF_URL=http://YOUR_VM_IP
```

For HTTPS with a domain:

```bash
flutter build apk --release \
  --dart-define=GEMMA4_BFF_URL=https://demo.yourdomain.com
```

The app will hit API gateway endpoints from the phone:

- `GET /health`
- `POST /prepare/session`
- `POST /prepare/stream`
- `POST /prepare/action`
- `POST /online/decision`
- `POST /online/calming-places`
- `GET /reflect/day`
- `POST /reflect/action`
- `WS /online/ws`

## Restart Behavior

The VM disk keeps Postgres data, graph-memory files, models, and the repo. The
systemd units restart MCP, ADK, BFF, and optional vLLM after boot.

Useful commands:

```bash
sudo systemctl status margadeep-mcp margadeep-adk margadeep-bff margadeep-vllm
journalctl -u margadeep-bff -f
journalctl -u margadeep-adk -f
journalctl -u margadeep-mcp -f
journalctl -u margadeep-vllm -f
```

## Demo Caveats

- This is a live demo deployment, not a production privacy/security posture.
- Add HTTPS before sharing outside your own devices.
- Add auth before letting real caregivers use real child data.
- The local Postgres path still uses `psql` through `profile_episode_store.py`; the VM
  env file sets `PGHOST`, `PGUSER`, and `PGPASSWORD` so those subprocess calls
  can reach the local database.
