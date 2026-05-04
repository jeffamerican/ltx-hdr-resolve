param(
  [switch]$AllUsers,
  [switch]$CustomPaths,
  [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$HfBaseModelUrl = "https://huggingface.co/Lightricks/LTX-2.3"
$HfHdrModelUrl = "https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-HDR"
$HfHdrFilesUrl = "https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-HDR/tree/main"
$HfTokenUrl = "https://huggingface.co/settings/tokens/new?tokenType=read"
$MinimumFreeGb = 120

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

function Find-UvCommand {
  $uv = Get-Command uv -ErrorAction SilentlyContinue
  if ($uv) {
    return $uv.Source
  }

  $candidates = @(
    (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
    (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  return ""
}

function Invoke-Step {
  param(
    [string]$Description,
    [scriptblock]$Action
  )

  Write-Step $Description
  & $Action
  if ($LASTEXITCODE -ne 0) {
    throw "$Description failed with exit code $LASTEXITCODE"
  }
}

function Ensure-Uv {
  $uv = Find-UvCommand
  if (-not [string]::IsNullOrWhiteSpace($uv)) {
    Write-Ok "uv found: $uv"
    return $uv
  }

  Write-Step "Installing uv"
  $installer = Join-Path $env:TEMP "uv-installer.ps1"
  Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -OutFile $installer
  powershell -NoProfile -ExecutionPolicy Bypass -File $installer
  if ($LASTEXITCODE -ne 0) {
    throw "uv installer failed with exit code $LASTEXITCODE"
  }

  $uv = Find-UvCommand
  if ([string]::IsNullOrWhiteSpace($uv)) {
    throw "uv installed, but uv.exe was not found."
  }
  Write-Ok "uv installed: $uv"
  return $uv
}

function Assert-FreeSpace {
  param(
    [string]$Path,
    [int]$MinimumGb
  )

  $target = $Path
  while (-not (Test-Path $target)) {
    $parent = Split-Path -Parent $target
    if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $target) {
      break
    }
    $target = $parent
  }

  $root = [System.IO.Path]::GetPathRoot((Resolve-Path $target).Path)
  $drive = Get-PSDrive -Name $root.Substring(0, 1)
  $freeGb = [math]::Round($drive.Free / 1GB, 1)
  Write-Host "Free space on $root $freeGb GB"
  if ($freeGb -lt $MinimumGb) {
    throw "Not enough free disk space. The LTX HDR install needs at least $MinimumGb GB free on $root for model downloads, Python packages, caches, and generated EXR output."
  }
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

function Ensure-LtxCheckout {
  param(
    [string]$LtxRepo
  )

  $pipelineScript = Join-Path $LtxRepo "packages\ltx-pipelines\src\ltx_pipelines\hdr_ic_lora.py"
  if (Test-Path $pipelineScript) {
    Write-Ok "LTX checkout found: $LtxRepo"
    return
  }

  if ((Test-Path $LtxRepo) -and ((Get-ChildItem -Force -Path $LtxRepo | Select-Object -First 1) -ne $null)) {
    throw "LTX-Video folder exists but is not a usable checkout: $LtxRepo"
  }

  Write-Step "Downloading LTX-Video"
  $zipPath = Join-Path $env:TEMP "LTX-2-main.zip"
  $extractRoot = Join-Path $env:TEMP ("LTX-2-" + [guid]::NewGuid().ToString("N"))
  Invoke-WebRequest -Uri "https://github.com/Lightricks/LTX-2/archive/refs/heads/main.zip" -OutFile $zipPath
  Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force
  $downloadedRoot = Join-Path $extractRoot "LTX-2-main"
  if (-not (Test-Path (Join-Path $downloadedRoot "packages\ltx-pipelines\src\ltx_pipelines\hdr_ic_lora.py"))) {
    throw "Downloaded LTX-2 archive did not contain the HDR IC-LoRA pipeline."
  }

  if (Test-Path $LtxRepo) {
    Remove-Item -Path $LtxRepo -Recurse -Force
  }
  Move-Item -Path $downloadedRoot -Destination $LtxRepo
  Write-Ok "LTX-2 downloaded to: $LtxRepo"
}

function Ensure-LtxPythonEnvironment {
  param(
    [string]$Uv,
    [string]$LtxRepo,
    [string]$LtxPython
  )

  if (-not (Test-Path $LtxPython)) {
    Invoke-Step "Creating LTX Python 3.11 environment" {
      Push-Location $LtxRepo
      try {
        & $Uv venv --python 3.11
      } finally {
        Pop-Location
      }
    }
  } else {
    Write-Ok "LTX Python environment found: $LtxPython"
  }

  Invoke-Step "Installing LTX Python packages" {
    Push-Location $LtxRepo
    try {
      & $Uv sync --frozen
      if ($LASTEXITCODE -eq 0) {
        & $Uv pip install --python $LtxPython requests
      }
    } finally {
      Pop-Location
    }
  }
}

function Get-HuggingFaceToken {
  if (-not [string]::IsNullOrWhiteSpace($env:HF_TOKEN)) {
    Write-Ok "Using Hugging Face token from HF_TOKEN environment variable"
    return $env:HF_TOKEN
  }

  Write-Warn "The LTX Hugging Face model repositories are gated."
  Write-Host ""
  Write-Host "Before downloads can start, your Hugging Face account must have access to:"
  Write-Host "  1. $HfBaseModelUrl"
  Write-Host "  2. $HfHdrModelUrl"
  Write-Host ""
  Write-Host "On the HDR page, complete the access form/request button. The Files tab must be visible before downloads will work:"
  Write-Host "  $HfHdrFilesUrl"
  Write-Host ""
  Write-Host "Then create or use a read token here:"
  Write-Host "  $HfTokenUrl"
  Write-Host ""
  $openAnswer = Read-Host "Open these Hugging Face pages now? [Y/n]"
  if ([string]::IsNullOrWhiteSpace($openAnswer) -or $openAnswer.ToLowerInvariant().StartsWith("y")) {
    Start-Process $HfBaseModelUrl
    Start-Process $HfHdrModelUrl
    Start-Process $HfHdrFilesUrl
    Start-Process $HfTokenUrl
    Write-Host ""
    Write-Host "Complete the HDR model access form/request in the browser, verify the Files tab opens, create/copy a read token, then return here."
  }

  Write-Host ""
  Write-Host "Paste the Hugging Face read token and press Enter."
  Write-Warn "The token will be visible while pasting. The installer does not save it."
  $token = Read-Host "Hugging Face token"
  if ([string]::IsNullOrWhiteSpace($token)) {
    throw "A Hugging Face token is required to download the gated LTX model files."
  }
  return $token.Trim()
}

function Ensure-Models {
  param(
    [string]$LtxPython,
    [string]$ModelDir,
    [string]$RepoRoot
  )

  $missingBefore = Get-MissingRuntimeInputs "" "" $ModelDir | Where-Object { $_.StartsWith("Model file:") }
  if ($missingBefore.Count -eq 0) {
    Write-Ok "All model files found in: $ModelDir"
    return
  }

  Write-Step "Downloading LTX model files"
  $token = Get-HuggingFaceToken

  & $LtxPython (Join-Path $RepoRoot "src\download_models.py") --output-dir $ModelDir --token $token
  if ($LASTEXITCODE -ne 0) {
    throw "Model download failed. Confirm access is accepted for $HfBaseModelUrl and $HfHdrModelUrl, then rerun the installer."
  }
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
  if (-not [string]::IsNullOrWhiteSpace($LtxRepo) -and -not (Test-Path $LtxRepo)) {
    $missing += "LTX checkout folder: $LtxRepo"
  }
  if (-not [string]::IsNullOrWhiteSpace($LtxPython) -and -not (Test-Path $LtxPython)) {
    $missing += "LTX Python executable: $LtxPython"
  }

  if (-not [string]::IsNullOrWhiteSpace($LtxRepo)) {
    $ltxScript = Join-Path $LtxRepo "packages\ltx-pipelines\src\ltx_pipelines\hdr_ic_lora.py"
    if (-not (Test-Path $ltxScript)) {
      $missing += "LTX HDR pipeline: $ltxScript"
    }
  }

  $modelFiles = @(
    "ltx-2.3-22b-distilled-1.1.safetensors",
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

  Write-Step "Checking disk space"
  Write-Warn "LTX HDR uses very large model files and EXR outputs. Keep at least $MinimumFreeGb GB free on the install drive."
  Assert-FreeSpace $RepoRoot $MinimumFreeGb

  $uv = Ensure-Uv
  Ensure-LtxCheckout $ltxRepo
  Ensure-LtxPythonEnvironment $uv $ltxRepo $ltxPython
  Ensure-Models $ltxPython $modelDir $RepoRoot

  $config = [ordered]@{
    ltx_repo_path = $ltxRepo
    ltx_python = $ltxPython
    ltx_hdr_script = "packages\ltx-pipelines\src\ltx_pipelines\hdr_ic_lora.py"
    output_root = $outputRoot
    distilled_checkpoint = Join-Path $modelDir "ltx-2.3-22b-distilled-1.1.safetensors"
    upscaler = Join-Path $modelDir "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
    lora = Join-Path $modelDir "ltx-2.3-22b-ic-lora-hdr-0.9.safetensors"
    text_embeddings = Join-Path $modelDir "ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors"
    exr_half = $true
    high_quality = $false
    skip_mp4 = $true
    no_save_exr = $false
    seed = 10
    max_frames = 49
    extra_env = @{}
  }

  Write-LtxConfig $ConfigPath ([pscustomobject]$config)
  Write-Ok "Wrote $ConfigPath"

  Write-Step "Checking local runtime"
  $missingInputs = Get-MissingRuntimeInputs $ltxRepo $ltxPython $modelDir
  if ($missingInputs.Count -gt 0) {
    Write-Warn "Local LTX runtime is not ready yet."
    Write-Host ""
    Write-Host "Missing files/folders:"
    foreach ($missingInput in $missingInputs) {
      Write-Host "  - $missingInput"
    }
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
