param(
  [switch]$AllUsers,
  [switch]$SkipNotepad,
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

try {
  $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
  $ConfigDir = Join-Path $env:USERPROFILE ".ltx-hdr-resolve"
  $ConfigPath = Join-Path $ConfigDir "config.json"
  $TemplatePath = Join-Path $RepoRoot "config\config.example.windows.json"

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

  $createdConfig = $false
  if (-not (Test-Path $ConfigPath)) {
    Copy-Item -Path $TemplatePath -Destination $ConfigPath
    $createdConfig = $true
    Write-Ok "Created $ConfigPath"
  } else {
    Write-Ok "Config already exists at $ConfigPath"
  }

  $configText = Get-Content -Raw -Path $ConfigPath
  $needsEditing = $createdConfig -or $configText.Contains("YourName") -or $configText.Contains("D:\LTX_Models")

  if ($needsEditing) {
    Write-Warn "Config still contains example paths."
    Write-Host "Set these paths before running a conversion:"
    Write-Host "  - ltx_repo_path"
    Write-Host "  - ltx_python"
    Write-Host "  - output_root"
    Write-Host "  - the four model file paths"

    if (-not $SkipNotepad) {
      Write-Host ""
      Write-Host "Opening config in Notepad. Save it, then close Notepad to continue."
      Start-Process notepad.exe -ArgumentList "`"$ConfigPath`"" -Wait
      $configText = Get-Content -Raw -Path $ConfigPath
      $needsEditing = $configText.Contains("YourName") -or $configText.Contains("D:\LTX_Models")
    }
  }

  Write-Step "Checking local runtime"
  $pythonCommand = Find-PythonCommand
  if ($pythonCommand.Count -eq 0) {
    Write-Warn "Python was not found on PATH. Install Python 3.11, then run this installer again."
  } elseif ($needsEditing) {
    Write-Warn "Skipping diagnostic because config still has example paths."
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
