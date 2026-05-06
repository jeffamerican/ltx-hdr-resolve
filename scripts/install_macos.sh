#!/usr/bin/env bash
set -euo pipefail

MODE="Cloud"
CUSTOM_PATHS=0
NO_PAUSE=0
LTX_API_KEY_URL="https://app.ltx.video/"
MINIMUM_CLOUD_FREE_GB=10

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cloud)
      MODE="Cloud"
      ;;
    --custom-paths)
      CUSTOM_PATHS=1
      ;;
    --no-pause)
      NO_PAUSE=1
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${HOME}/.ltx-hdr-resolve"
CONFIG_PATH="${CONFIG_DIR}/config.json"
SECRETS_PATH="${CONFIG_DIR}/secrets.json"
CLOUD_RUNTIME_DIR="${REPO_ROOT}/.cloud-venv"
LTX_REPO_DEFAULT="${REPO_ROOT}/LTX-Video"
MODEL_DIR_DEFAULT="${REPO_ROOT}/models"
OUTPUT_ROOT_DEFAULT="${REPO_ROOT}/output"
UV_PATH=""
CLOUD_PYTHON_PATH=""
LTX_API_KEY_RESULT=""

write_step() {
  echo
  echo "==> $1"
}

write_ok() {
  echo "OK: $1"
}

write_warn() {
  echo "WARN: $1"
}

pause_if_needed() {
  if [[ "${NO_PAUSE}" != "1" ]]; then
    echo
    read -r -p "Press Enter to close this installer..."
  fi
}

trap 'pause_if_needed' EXIT

read_path_default() {
  local label="$1"
  local default_value="$2"
  echo
  echo "${label}"
  read -r -p "[${default_value}] " answer
  if [[ -z "${answer}" ]]; then
    echo "${default_value}"
  else
    echo "${answer/#\~/${HOME}}"
  fi
}

find_uv() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return
  fi
  for candidate in "${HOME}/.local/bin/uv" "${HOME}/.cargo/bin/uv"; do
    if [[ -x "${candidate}" ]]; then
      echo "${candidate}"
      return
    fi
  done
}

ensure_uv() {
  local uv
  uv="$(find_uv || true)"
  if [[ -n "${uv}" ]]; then
    write_ok "uv found: ${uv}"
    UV_PATH="${uv}"
    return
  fi

  write_step "Installing uv"
  local installer
  installer="$(mktemp -t uv-installer.XXXXXX.sh)"
  curl -LsSf https://astral.sh/uv/install.sh -o "${installer}"
  sh "${installer}"
  uv="$(find_uv || true)"
  if [[ -z "${uv}" ]]; then
    echo "uv installed, but the uv command was not found." >&2
    exit 1
  fi
  write_ok "uv installed: ${uv}"
  UV_PATH="${uv}"
}

assert_free_space() {
  local path="$1"
  local minimum_gb="$2"
  mkdir -p "${path}"
  local available_kb
  available_kb="$(df -Pk "${path}" | awk 'NR==2 {print $4}')"
  local available_gb
  available_gb=$((available_kb / 1024 / 1024))
  echo "Free space near ${path}: ${available_gb} GB"
  if (( available_gb < minimum_gb )); then
    echo "Not enough free disk space. LTX HDR cloud mode needs at least ${minimum_gb} GB free for Python runtime, logs, and EXR output." >&2
    exit 1
  fi
}

ensure_cloud_python_environment() {
  local uv="$1"
  local runtime_dir="$2"
  local python="${runtime_dir}/bin/python"
  if [[ -x "${python}" ]]; then
    write_ok "Cloud Python environment found: ${python}"
    CLOUD_PYTHON_PATH="${python}"
    return
  fi

  write_step "Creating cloud Python 3.11 environment"
  "${uv}" venv --python 3.11 "${runtime_dir}"
  if [[ ! -x "${python}" ]]; then
    echo "Cloud Python environment was created, but Python was not found: ${python}" >&2
    exit 1
  fi
  CLOUD_PYTHON_PATH="${python}"
}

get_ltx_api_key() {
  if [[ -n "${LTX_API_KEY:-}" ]]; then
    write_ok "Using LTX API key from LTX_API_KEY environment variable"
    LTX_API_KEY_RESULT="${LTX_API_KEY}"
    return
  fi
  if [[ -n "${LTXV_API_KEY:-}" ]]; then
    write_ok "Using LTX API key from LTXV_API_KEY environment variable"
    LTX_API_KEY_RESULT="${LTXV_API_KEY}"
    return
  fi

  if [[ -f "${SECRETS_PATH}" ]]; then
    local existing
    existing="$("${CLOUD_PYTHON_PATH}" - "${SECRETS_PATH}" <<'PY' || true
import json
import sys

try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print((data.get("ltx_api_key") or "").strip())
except Exception:
    pass
PY
)"
    if [[ -n "${existing}" ]]; then
      write_ok "Existing LTX API key found: ${SECRETS_PATH}"
      read -r -p "Change the saved LTX API key now? [y/N] " change
      if [[ -z "${change}" || ! "${change}" =~ ^[Yy] ]]; then
        LTX_API_KEY_RESULT="${existing}"
        return
      fi
    fi
  fi

  write_step "LTX cloud API key"
  echo "Create or copy your LTX API key here:"
  echo "  ${LTX_API_KEY_URL}"
  read -r -p "Open the LTX API key page now? [Y/n] " open_answer
  if [[ -z "${open_answer}" || "${open_answer}" =~ ^[Yy] ]]; then
    open "${LTX_API_KEY_URL}" || true
  fi
  echo
  echo "Paste the LTX API key and press Enter."
  write_warn "The key will be visible while pasting. It will be saved locally at ${SECRETS_PATH}."
  read -r -p "LTX API key: " key
  if [[ -z "${key// }" ]]; then
    echo "An LTX API key is required for cloud mode." >&2
    exit 1
  fi
  LTX_API_KEY_RESULT="${key}"
}

write_json_files() {
  local ltx_python="$1"
  local output_root="$2"
  local api_key="$3"
  mkdir -p "${CONFIG_DIR}" "${output_root}"
  CONFIG_PATH="${CONFIG_PATH}" \
  SECRETS_PATH="${SECRETS_PATH}" \
  REPO_ROOT="${REPO_ROOT}" \
  LTX_PYTHON="${ltx_python}" \
  OUTPUT_ROOT="${output_root}" \
  LTX_API_KEY_VALUE="${api_key}" \
  "${ltx_python}" - <<'PY'
import json
import os
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
config_path = Path(os.environ["CONFIG_PATH"])
secrets_path = Path(os.environ["SECRETS_PATH"])
config = {
    "mode": "ltx_cloud",
    "ltx_repo_path": str(repo / "LTX-Video"),
    "ltx_python": os.environ["LTX_PYTHON"],
    "ltx_hdr_script": "packages/ltx-pipelines/src/ltx_pipelines/hdr_ic_lora.py",
    "cloud_api_key_path": str(secrets_path),
    "cloud_upload_limit_mb": 100,
    "cloud_segment_frames": 0,
    "cloud_poll_seconds": 5,
    "cloud_timeout_seconds": 1800,
    "output_root": os.environ["OUTPUT_ROOT"],
    "distilled_checkpoint": str(repo / "models" / "ltx-2.3-22b-distilled-1.1.safetensors"),
    "upscaler": str(repo / "models" / "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"),
    "lora": str(repo / "models" / "ltx-2.3-22b-ic-lora-hdr-0.9.safetensors"),
    "text_embeddings": str(repo / "models" / "ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors"),
    "exr_half": True,
    "high_quality": False,
    "skip_mp4": True,
    "no_save_exr": False,
    "seed": 10,
    "max_frames": 49,
    "spatial_tile": 768,
    "offload": "cpu",
    "extra_env": {},
}
config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
secrets_path.write_text(json.dumps({"ltx_api_key": os.environ["LTX_API_KEY_VALUE"]}, indent=2) + "\n", encoding="utf-8")
PY
  chmod 600 "${SECRETS_PATH}" || true
}

main() {
  echo "LTX HDR Resolve macOS Installer"
  echo "Repo: ${REPO_ROOT}"
  echo "Mode: ${MODE}"
  if [[ "${MODE}" != "Cloud" ]]; then
    echo "macOS one-click installer currently supports cloud mode. Use docs/local-ltx-setup.md for local GPU mode." >&2
    exit 2
  fi

  write_step "Installing DaVinci Resolve menu script"
  "${REPO_ROOT}/scripts/install_resolve_script.sh"
  write_ok "Resolve menu script installed"

  local output_root="${OUTPUT_ROOT_DEFAULT}"
  if [[ "${CUSTOM_PATHS}" == "1" ]]; then
    output_root="$(read_path_default "Output folder for LTX HDR jobs" "${OUTPUT_ROOT_DEFAULT}")"
  else
    echo "Using local folders next to this installer:"
    echo "  Python runtime: ${CLOUD_RUNTIME_DIR}"
    echo "  Output:         ${output_root}"
  fi

  write_step "Checking disk space"
  write_warn "LTX HDR cloud mode keeps Python runtime, uploads, logs, and EXR outputs locally. Keep at least ${MINIMUM_CLOUD_FREE_GB} GB free."
  assert_free_space "${REPO_ROOT}" "${MINIMUM_CLOUD_FREE_GB}"

  ensure_uv
  ensure_cloud_python_environment "${UV_PATH}" "${CLOUD_RUNTIME_DIR}"
  get_ltx_api_key
  write_json_files "${CLOUD_PYTHON_PATH}" "${output_root}" "${LTX_API_KEY_RESULT}"
  write_ok "Saved LTX API key to ${SECRETS_PATH}"
  write_ok "Wrote ${CONFIG_PATH}"

  write_step "Checking runtime"
  "${CLOUD_PYTHON_PATH}" "${REPO_ROOT}/src/ltx_hdr_worker.py" diagnose --config "${CONFIG_PATH}"
  write_ok "LTX HDR config validated"

  write_step "Done"
  echo "Restart DaVinci Resolve."
  echo "Then run: Workspace -> Scripts -> Utility -> LTX HDR Convert Current Clip"
  echo
  echo "Config file:"
  echo "  ${CONFIG_PATH}"
}

main "$@"
