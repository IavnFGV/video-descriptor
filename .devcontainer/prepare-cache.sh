#!/usr/bin/env bash
set -euo pipefail

# Only change ownership of this project's cache volumes.
for cache_dir in "${PIP_CACHE_DIR:-$HOME/.cache/pip}" "${HF_HOME:-$HOME/.cache/huggingface}"; do
  sudo mkdir -p "$cache_dir"
  sudo chown -R "$(id -u):$(id -g)" "$cache_dir"
done
