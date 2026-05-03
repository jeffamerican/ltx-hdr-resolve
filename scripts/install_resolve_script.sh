#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${HOME}/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
DEST_FILE="${DEST_DIR}/LTX HDR Convert Current Clip.py"
PLUGIN_ROOT_JSON="$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "${PLUGIN_ROOT}")"

mkdir -p "${DEST_DIR}"

cat > "${DEST_FILE}" <<PY
#!/usr/bin/env python3

import os
import sys

os.environ["LTX_HDR_PLUGIN_ROOT"] = ${PLUGIN_ROOT_JSON}
sys.path.insert(0, os.path.join(os.environ["LTX_HDR_PLUGIN_ROOT"], "resolve_scripts"))

from ltx_hdr_resolve import main

main()
PY

echo "Installed Resolve script:"
echo "${DEST_FILE}"
echo
echo "Restart Resolve, then run Workspace -> Scripts -> Utility -> LTX HDR Convert Current Clip"
