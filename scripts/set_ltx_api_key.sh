#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${HOME}/.ltx-hdr-resolve"
SECRETS_PATH="${CONFIG_DIR}/secrets.json"
LTX_API_KEY_URL="https://app.ltx.video/"
NO_PAUSE=0

for arg in "$@"; do
  case "${arg}" in
    --no-pause)
      NO_PAUSE=1
      ;;
    *)
      echo "Unknown option: ${arg}" >&2
      exit 2
      ;;
  esac
done

pause_if_needed() {
  if [[ "${NO_PAUSE}" != "1" ]]; then
    echo
    read -r -p "Press Enter to close..."
  fi
}

open_ltx_key_page() {
  echo
  echo "Create or copy your LTX API key here:"
  echo "  ${LTX_API_KEY_URL}"
  read -r -p "Open the LTX API key page now? [Y/n] " answer
  if [[ -z "${answer}" || "${answer}" =~ ^[Yy] ]]; then
    open "${LTX_API_KEY_URL}" || true
  fi
}

find_python() {
  local config_path="${CONFIG_DIR}/config.json"
  if [[ -f "${config_path}" ]]; then
    local configured_python
    configured_python="$(sed -n 's/^[[:space:]]*"ltx_python"[[:space:]]*:[[:space:]]*"\(.*\)"[[:space:]]*,\{0,1\}[[:space:]]*$/\1/p' "${config_path}" | head -n 1)"
    if [[ -n "${configured_python}" && -x "${configured_python}" ]]; then
      echo "${configured_python}"
      return
    fi
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
}

write_secret() {
  local key="$1"
  local python_cmd
  python_cmd="$(find_python || true)"
  mkdir -p "${CONFIG_DIR}"
  if [[ -n "${python_cmd}" ]]; then
    SECRETS_PATH="${SECRETS_PATH}" LTX_KEY="${key}" "${python_cmd}" - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["SECRETS_PATH"])
path.write_text(json.dumps({"ltx_api_key": os.environ["LTX_KEY"]}, indent=2) + "\n", encoding="utf-8")
PY
  else
    local escaped
    escaped="${key//\\/\\\\}"
    escaped="${escaped//\"/\\\"}"
    printf '{\n  "ltx_api_key": "%s"\n}\n' "${escaped}" > "${SECRETS_PATH}"
  fi
  chmod 600 "${SECRETS_PATH}" || true
}

trap 'pause_if_needed' EXIT

echo "LTX HDR Resolve API Key Setup"
echo "Secrets file: ${SECRETS_PATH}"
open_ltx_key_page
echo
echo "Paste the LTX API key and press Enter."
echo "The key will be visible while pasting. It will be saved locally."
read -r -p "LTX API key: " api_key
if [[ -z "${api_key// }" ]]; then
  echo "No API key entered." >&2
  exit 1
fi

write_secret "${api_key}"
echo "OK: Saved LTX API key to ${SECRETS_PATH}"
