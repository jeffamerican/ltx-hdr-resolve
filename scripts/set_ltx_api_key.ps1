param(
  [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$ConfigDir = Join-Path $env:USERPROFILE ".ltx-hdr-resolve"
$SecretsPath = Join-Path $ConfigDir "secrets.json"
$LtxApiKeyUrl = "https://app.ltx.video/"

function Pause-IfNeeded {
  if (-not $NoPause) {
    Write-Host ""
    Write-Host "Press Enter to close..."
    [void][System.Console]::ReadLine()
  }
}

try {
  New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null

  Write-Host "LTX HDR Resolve API Key Setup" -ForegroundColor White
  Write-Host ""
  Write-Host "Create or copy your LTX API key here:"
  Write-Host "  $LtxApiKeyUrl"
  Write-Host ""
  $openAnswer = Read-Host "Open the LTX API key page now? [Y/n]"
  if ([string]::IsNullOrWhiteSpace($openAnswer) -or $openAnswer.ToLowerInvariant().StartsWith("y")) {
    Start-Process $LtxApiKeyUrl
  }

  Write-Host ""
  Write-Host "Paste the LTX API key and press Enter."
  Write-Warning "The key will be visible while pasting. It will be saved locally at $SecretsPath."
  $key = Read-Host "LTX API key"
  if ([string]::IsNullOrWhiteSpace($key)) {
    throw "No LTX API key was entered."
  }

  $secrets = [ordered]@{
    ltx_api_key = $key.Trim()
  }
  $json = $secrets | ConvertTo-Json -Depth 5
  $utf8NoBom = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($SecretsPath, $json, $utf8NoBom)

  Write-Host ""
  Write-Host "OK: saved LTX API key to $SecretsPath" -ForegroundColor Green
  Pause-IfNeeded
  exit 0
} catch {
  Write-Host ""
  Write-Host "FAILED" -ForegroundColor Red
  Write-Host $_.Exception.Message -ForegroundColor Red
  Pause-IfNeeded
  exit 1
}
