#!/usr/bin/env bash
set -euo pipefail

source /etc/margadeep/margadeep.env

if [[ "${VLLM_SERVING_MODE:-python}" == "container" ]]; then
  IMAGE_URI="${VLLM_CONTAINER_IMAGE_URI:-gemma-e2b-mtp-vllm:local}"
  CONTAINER_NAME="${VLLM_CONTAINER_NAME:-margadeep-gemma4-vllm}"
  HF_CACHE_DIR="${HF_CACHE_DIR:-/opt/margadeep/hf-cache}"
  SHM_SIZE="${VLLM_SHM_SIZE:-16g}"
  GPU_DEVICES="${VLLM_GPU_DEVICES:-device=0}"
  HOST_PORT="${VLLM_PORT:-8000}"
  CONTAINER_PORT="${VLLM_CONTAINER_PORT:-8080}"

  mkdir -p "${HF_CACHE_DIR}"
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

  DOCKER_ARGS=(
    docker
    run
    --rm
    "--name=${CONTAINER_NAME}"
    --ipc=host
    "--shm-size=${SHM_SIZE}"
    --gpus
    "${GPU_DEVICES}"
    -p
    "127.0.0.1:${HOST_PORT}:${CONTAINER_PORT}"
    -v
    "${HF_CACHE_DIR}:/root/.cache/huggingface"
    -e
    "HOST=0.0.0.0"
    -e
    "PORT=${CONTAINER_PORT}"
    -e
    "MODEL_ID=${VLLM_MODEL}"
    -e
    "SERVED_MODEL_NAME=${VLLM_SERVED_MODEL_NAME:-${VLLM_MODEL}}"
    -e
    "TENSOR_PARALLEL_SIZE=${VLLM_TENSOR_PARALLEL_SIZE:-1}"
    -e
    "MAX_MODEL_LEN=${VLLM_MAX_MODEL_LEN:-8192}"
    -e
    "GPU_MEMORY_UTILIZATION=${VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
    -e
    "ENABLE_MTP=${VLLM_ENABLE_MTP:-0}"
    -e
    "SPECULATIVE_NUM_TOKENS=${VLLM_SPECULATIVE_NUM_TOKENS:-4}"
    -e
    "SPECULATIVE_ASSISTANT_MODEL=${VLLM_SPECULATIVE_ASSISTANT_MODEL:-google/gemma-4-E2B-it-assistant}"
    -e
    "QUANTIZATION=${VLLM_QUANTIZATION:-none}"
    -e
    "KV_CACHE_DTYPE=${VLLM_KV_CACHE_DTYPE:-auto}"
    -e
    "LIMIT_MM_PER_PROMPT=${VLLM_LIMIT_MM_PER_PROMPT:-{\"image\":0,\"audio\":0}}"
    -e
    "ENABLE_PREFIX_CACHING=${VLLM_ENABLE_PREFIX_CACHING:-1}"
    -e
    "ENABLE_CHUNKED_PREFILL=${VLLM_ENABLE_CHUNKED_PREFILL:-1}"
    -e
    "ENABLE_ASYNC_SCHEDULING=${VLLM_ENABLE_ASYNC_SCHEDULING:-1}"
    -e
    "DISABLE_LOG_REQUESTS=${VLLM_DISABLE_LOG_REQUESTS:-1}"
  )

  if [[ -n "${VLLM_MAX_NUM_SEQS:-}" ]]; then
    DOCKER_ARGS+=(-e "MAX_NUM_SEQS=${VLLM_MAX_NUM_SEQS}")
  fi

  if [[ -n "${VLLM_MAX_NUM_BATCHED_TOKENS:-}" ]]; then
    DOCKER_ARGS+=(-e "MAX_NUM_BATCHED_TOKENS=${VLLM_MAX_NUM_BATCHED_TOKENS}")
  fi

  if [[ -n "${HF_TOKEN:-}" ]]; then
    DOCKER_ARGS+=(-e HF_TOKEN)
  fi

  if [[ -n "${HF_TOKEN_SECRET_RESOURCE:-}" ]]; then
    DOCKER_ARGS+=(-e "HF_TOKEN_SECRET_RESOURCE=${HF_TOKEN_SECRET_RESOURCE}")
  fi

  if [[ -n "${VLLM_EXTRA_ARGS:-}" ]]; then
    DOCKER_ARGS+=(-e "EXTRA_VLLM_ARGS=${VLLM_EXTRA_ARGS}")
  fi

  exec "${DOCKER_ARGS[@]}" "${IMAGE_URI}"
fi

exec /opt/margadeep/vllm/bin/python -m vllm.entrypoints.openai.api_server \
  --host "${VLLM_HOST:-127.0.0.1}" \
  --port "${VLLM_PORT:-8000}" \
  --model "${VLLM_MODEL}" \
  --served-model-name "${VLLM_SERVED_MODEL_NAME:-${VLLM_MODEL}}" \
  --max-model-len "${VLLM_MAX_MODEL_LEN:-8192}" \
  --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION:-0.88}"
