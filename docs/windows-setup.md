# Windows Setup

This plugin is designed to run the LTX HDR conversion locally on the Windows workstation.

## 1. Prepare LTX locally

Install Python 3.11, Git, and `uv`, then clone LTX:

```powershell
git clone https://github.com/Lightricks/LTX-Video.git C:\Users\YourName\src\LTX-Video
cd C:\Users\YourName\src\LTX-Video
uv venv --python 3.11
.\.venv\Scripts\Activate.ps1
uv pip install -e packages/ltx-core -e packages/ltx-pipelines -e packages/ltx-trainer
```

Download the four model files listed in [local-ltx-setup.md](local-ltx-setup.md), for example into `D:\LTX_Models`.

## 2. Configure the plugin

The easy path is to double-click this file from the repository root:

```text
Install-Windows.cmd
```

It installs the Resolve menu script, creates the config file if needed, opens the config in Notepad, and runs the diagnostic when the example paths have been replaced.

Manual equivalent from this repository:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ltx-hdr-resolve"
Copy-Item .\config\config.example.windows.json "$env:USERPROFILE\.ltx-hdr-resolve\config.json"
notepad "$env:USERPROFILE\.ltx-hdr-resolve\config.json"
```

Update every path in the config to match the local machine.

## 3. Diagnose before opening Resolve

```powershell
.\scripts\diagnose_local_runtime.ps1
```

Then test with a short SDR MP4:

```powershell
python .\src\ltx_hdr_worker.py convert `
  --config "$env:USERPROFILE\.ltx-hdr-resolve\config.json" `
  --input "D:\TestClips\short-test.mp4" `
  --clip-name short-test
```

The command prints a `manifest.json` path. Open that file and confirm `status` is `completed` and `exr_frame_count` is greater than zero.

## 4. Install the Resolve menu script

Current user install:

```powershell
.\Install-Windows.cmd
```

All-users install, from an elevated PowerShell:

```powershell
.\scripts\install_windows.ps1 -AllUsers
```

Restart Resolve. The command appears under:

```text
Workspace -> Scripts -> Utility -> LTX HDR Convert Current Clip
```

## Resolve script locations

Resolve scans these Windows script folders on startup:

- Current user: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility`
- All users: `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility`

Use the current-user install unless you want every Windows account on the machine to see the script.
