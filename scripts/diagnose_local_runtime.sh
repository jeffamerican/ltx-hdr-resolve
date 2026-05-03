#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-${HOME}/.ltx-hdr-resolve/config.json}"
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${PLUGIN_ROOT}/src/ltx_hdr_worker.py" diagnose --config "${CONFIG_PATH}"
