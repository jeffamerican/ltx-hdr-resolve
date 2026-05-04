param(
  [switch]$AllUsers
)

$ErrorActionPreference = "Stop"

$PluginRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($AllUsers) {
  $DestDir = Join-Path $env:ProgramData "Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility"
} else {
  $DestDir = Join-Path $env:APPDATA "Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility"
}

$DestFile = Join-Path $DestDir "LTX HDR Convert Current Clip.py"
$DebugFile = Join-Path $DestDir "LTX HDR Debug Environment.py"
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

$PluginRootLiteral = $PluginRoot.Replace("\", "\\")

@"
#!/usr/bin/env python3

import os
import sys

os.environ["LTX_HDR_PLUGIN_ROOT"] = "$PluginRootLiteral"
sys.path.insert(0, os.path.join(os.environ["LTX_HDR_PLUGIN_ROOT"], "resolve_scripts"))

import ltx_hdr_resolve

for name in ("resolve", "fusion", "bmd"):
    if name in globals():
        setattr(ltx_hdr_resolve, name, globals()[name])

ltx_hdr_resolve.main()
"@ | Set-Content -Encoding UTF8 -Path $DestFile

@"
#!/usr/bin/env python3

import os
import sys

os.environ["LTX_HDR_PLUGIN_ROOT"] = "$PluginRootLiteral"
sys.path.insert(0, os.path.join(os.environ["LTX_HDR_PLUGIN_ROOT"], "resolve_scripts"))

import ltx_hdr_resolve

for name in ("resolve", "fusion", "bmd"):
    if name in globals():
        setattr(ltx_hdr_resolve, name, globals()[name])

ltx_hdr_resolve.debug_environment()
"@ | Set-Content -Encoding UTF8 -Path $DebugFile

Write-Host "Installed Resolve script:"
Write-Host $DestFile
Write-Host $DebugFile
Write-Host ""
Write-Host "Restart Resolve, then run Workspace -> Scripts -> Utility -> LTX HDR Convert Current Clip"
