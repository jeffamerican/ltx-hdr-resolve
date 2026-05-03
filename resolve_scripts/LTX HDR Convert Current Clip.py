#!/usr/bin/env python3

import os
import sys


PLUGIN_ROOT = os.environ.get("LTX_HDR_PLUGIN_ROOT", os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "resolve_scripts"))

from ltx_hdr_resolve import main


main()
