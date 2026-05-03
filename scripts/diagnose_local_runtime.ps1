param(
  [string]$ConfigPath = "$env:USERPROFILE\.ltx-hdr-resolve\config.json"
)

$ErrorActionPreference = "Stop"

$PluginRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
python "$PluginRoot\src\ltx_hdr_worker.py" diagnose --config "$ConfigPath"
