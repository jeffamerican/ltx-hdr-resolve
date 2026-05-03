param(
  [switch]$AllUsers,
  [switch]$NoPause
)

$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
  param([string]$Message)
  Write-Host "OK: $Message" -ForegroundColor Green
}

function Write-Warn {
  param([string]$Message)
  Write-Host "WARN: $Message" -ForegroundColor Yellow
}

function Pause-IfNeeded {
  if (-not $NoPause) {
    Write-Host ""
    Write-Host "Press Enter to close this installer..."
    [void][System.Console]::ReadLine()
  }
}

function Find-PythonCommand {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    return @($py.Source, "-3")
  }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return @($python.Source)
  }

  return @()
}

function Clean-PathInput {
  param([string]$Value)
  return [Environment]::ExpandEnvironmentVariables($Value.Trim().Trim('"'))
}

function Read-PathDefault {
  param(
    [string]$Label,
    [string]$DefaultValue
  )

  Write-Host ""
  Write-Host $Label -ForegroundColor White
  $answer = Read-Host "[$DefaultValue]"
  if ([string]::IsNullOrWhiteSpace($answer)) {
    return (Clean-PathInput $DefaultValue)
  }
  return (Clean-PathInput $answer)
}

function Read-ExistingConfig {
  param([string]$Path)

  if (-not (Test-Path $Path)) {
    return $null
  }

  try {
    return (Get-Content -Raw -Path $Path | ConvertFrom-Json)
  } catch {
    Write-Warn "Existing config is not valid JSON. The installer will rewrite it."
    return $null
  }
}

function Get-ConfigValue {
  param(
    [object]$Config,
    [string]$Name,
    [string]$Fallback
  )

  if ($null -eq $Config) {
    return $Fallback
  }

  $property = $Config.PSObject.Properties[$Name]
  if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
    return $Fallback
  }

  $value = [string]$property.Value
  if (
    $value.Contains("YourName") -or
    $value.Contains("/absolute/path") -or
    $value.Contains("D:\LTX_Models") -or
    $value.Contains("D:\LTX_HDR_Output")
  ) {
    return $Fallback
  }

  return $value
}

function Get-DefaultModelDir {
  param(
    [object]$Config,
    [string]$RepoRoot
  )

  $existingLora = Get-ConfigValue $Config "lora" ""
  if (-not [string]::IsNullOrWhiteSpace($existingLora)) {
    return (Split-Path -Parent $existingLora)
  }

  return (Join-Path $RepoRoot "models")
}

function Get-DefaultOutputDir {
  param(
    [object]$Config,
    [string]$RepoRoot
  )

  $existing = Get-ConfigValue $Config "output_root" ""
  if (-not [string]::IsNullOrWhiteSpace($existing)) {
    return $existing
  }

  return (Join-Path $RepoRoot "output")
}

function Write-LtxConfig {
  param(
    [string]$Path,
    [object]$Config
  )

  $json = $Config | ConvertTo-Json -Depth 5
  Set-Content -Path $Path -Value $json -Encoding UTF8
}

try {
  $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
  $ConfigDir = Join-Path $env:USERPROFILE ".ltx-hdr-resolve"
  $ConfigPath = Join-Path $ConfigDir "config.json"

  Write-Host "LTX HDR Resolve Windows Installer" -ForegroundColor White
  Write-Host "Repo: $RepoRoot"

  Write-Step "Installing DaVinci Resolve menu script"
  $installArgs = @()
  if ($AllUsers) {
    $installArgs += "-AllUsers"
  }
  & (Join-Path $RepoRoot "scripts\install_resolve_script.ps1") @installArgs
  Write-Ok "Resolve menu script installed"

  Write-Step "Preparing local config"
  New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null

  $existingConfig = Read-ExistingConfig $ConfigPath
  $defaultRepo = Get-ConfigValue $existingConfig "ltx_repo_path" (Join-Path $RepoRoot "LTX-Video")
  $ltxRepo = Read-PathDefault "LTX-Video folder" $defaultRepo

  $modelDir = Read-PathDefault "Folder containing the four LTX .safetensors model files" (Get-DefaultModelDir $existingConfig $RepoRoot)
  $outputRoot = Read-PathDefault "Output folder for LTX HDR jobs" (Get-DefaultOutputDir $existingConfig $RepoRoot)
  $ltxPython = Join-Path $ltxRepo ".venv\Scripts\python.exe"
  New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
  New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
  Write-Ok "Using LTX Python executable: $ltxPython"

  $config = [ordered]@{
    ltx_repo_path = $ltxRepo
    ltx_python = $ltxPython
    ltx_hdr_script = "run_hdr_ic_lora.py"
    output_root = $outputRoot
    distilled_checkpoint = Join-Path $modelDir "ltx-2.3-22b-distilled.safetensors"
    upscaler = Join-Path $modelDir "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
    lora = Join-Path $modelDir "ltx-2.3-22b-ic-lora-hdr-0.9.safetensors"
    text_embeddings = Join-Path $modelDir "ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors"
    exr_half = $true
    high_quality = $true
    skip_mp4 = $false
    no_save_exr = $false
    seed = 10
    max_frames = 161
    extra_env = @{}
  }

  Write-LtxConfig $ConfigPath ([pscustomobject]$config)
  Write-Ok "Wrote $ConfigPath"

  Write-Step "Checking local runtime"
  $pythonCommand = Find-PythonCommand
  if ($pythonCommand.Count -eq 0) {
    Write-Warn "Python was not found on PATH. Install Python 3.11, then run this installer again."
  } else {
    $pythonExe = $pythonCommand[0]
    $pythonArgs = @()
    if ($pythonCommand.Count -gt 1) {
      $pythonArgs += $pythonCommand[1..($pythonCommand.Count - 1)]
    }
    $pythonArgs += @(
      (Join-Path $RepoRoot "src\ltx_hdr_worker.py"),
      "diagnose",
      "--config",
      $ConfigPath
    )

    & $pythonExe @pythonArgs
    if ($LASTEXITCODE -eq 0) {
      Write-Ok "Local LTX HDR config validated"
    } else {
      Write-Warn "Diagnostic found missing paths or invalid settings. Fix config.json and run this installer again."
    }
  }

  Write-Step "Done"
  Write-Host "Restart DaVinci Resolve."
  Write-Host "Then run: Workspace -> Scripts -> Utility -> LTX HDR Convert Current Clip"
  Write-Host ""
  Write-Host "Config file:"
  Write-Host "  $ConfigPath"

  Pause-IfNeeded
  exit 0
} catch {
  Write-Host ""
  Write-Host "INSTALL FAILED" -ForegroundColor Red
  Write-Host $_.Exception.Message -ForegroundColor Red
  Pause-IfNeeded
  exit 1
}
