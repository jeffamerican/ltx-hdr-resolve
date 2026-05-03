param(
  [switch]$AllUsers,
  [switch]$CustomPaths,
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

function Write-LtxConfig {
  param(
    [string]$Path,
    [object]$Config
  )

  $json = $Config | ConvertTo-Json -Depth 5
  $utf8NoBom = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($Path, $json, $utf8NoBom)
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
    return [Environment]::ExpandEnvironmentVariables($DefaultValue.Trim().Trim('"'))
  }
  return [Environment]::ExpandEnvironmentVariables($answer.Trim().Trim('"'))
}

function Get-MissingRuntimeInputs {
  param(
    [string]$LtxRepo,
    [string]$LtxPython,
    [string]$ModelDir
  )

  $missing = @()
  if (-not (Test-Path $LtxRepo)) {
    $missing += "LTX checkout folder: $LtxRepo"
  }
  if (-not (Test-Path $LtxPython)) {
    $missing += "LTX Python executable: $LtxPython"
  }

  $ltxScript = Join-Path $LtxRepo "run_hdr_ic_lora.py"
  if (-not (Test-Path $ltxScript)) {
    $missing += "LTX HDR script: $ltxScript"
  }

  $modelFiles = @(
    "ltx-2.3-22b-distilled.safetensors",
    "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
    "ltx-2.3-22b-ic-lora-hdr-0.9.safetensors",
    "ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors"
  )
  foreach ($modelFile in $modelFiles) {
    $modelPath = Join-Path $ModelDir $modelFile
    if (-not (Test-Path $modelPath)) {
      $missing += "Model file: $modelPath"
    }
  }

  return $missing
}

try {
  $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
  $ConfigDir = Join-Path $env:USERPROFILE ".ltx-hdr-resolve"
  $ConfigPath = Join-Path $ConfigDir "config.json"
  $LtxRepoDefault = Join-Path $RepoRoot "LTX-Video"
  $ModelDirDefault = Join-Path $RepoRoot "models"
  $OutputRootDefault = Join-Path $RepoRoot "output"

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

  $ltxRepo = $LtxRepoDefault
  $modelDir = $ModelDirDefault
  $outputRoot = $OutputRootDefault
  if ($CustomPaths) {
    $ltxRepo = Read-PathDefault "LTX-Video folder" $LtxRepoDefault
    $modelDir = Read-PathDefault "Folder containing the four LTX .safetensors model files" $ModelDirDefault
    $outputRoot = Read-PathDefault "Output folder for LTX HDR jobs" $OutputRootDefault
  } else {
    Write-Host "Using local folders next to this installer:"
    Write-Host "  LTX checkout: $ltxRepo"
    Write-Host "  Models:       $modelDir"
    Write-Host "  Output:       $outputRoot"
  }

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
  $missingInputs = Get-MissingRuntimeInputs $ltxRepo $ltxPython $modelDir
  if ($missingInputs.Count -gt 0) {
    Write-Warn "Local LTX runtime is not ready yet. The Resolve script is installed and config.json was written."
    Write-Host ""
    Write-Host "Missing files/folders:"
    foreach ($missingInput in $missingInputs) {
      Write-Host "  - $missingInput"
    }
    Write-Host ""
    Write-Host "Next steps for the default install:"
    Write-Host "  1. Clone LTX into: $ltxRepo"
    Write-Host "  2. Create the LTX Python 3.11 venv inside that folder."
    Write-Host "  3. Put the four .safetensors files in: $modelDir"
    Write-Host "  4. Run Install-Windows.cmd again."
  } else {
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
