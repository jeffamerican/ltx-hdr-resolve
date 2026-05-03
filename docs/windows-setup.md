# Windows Setup

This plugin is designed to run the LTX HDR conversion locally on the Windows workstation.

## 1. Prepare LTX locally

Double-click `Install-Windows.cmd`. It installs `uv` if needed, downloads LTX, creates the Python 3.11 environment, installs LTX packages, and downloads the model files.

The only account step is Hugging Face model access. The installer opens these pages when needed:

- [LTX-2.3 base model](https://huggingface.co/Lightricks/LTX-2.3)
- [LTX HDR IC-LoRA model](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-HDR)
- [Create a Hugging Face read token](https://huggingface.co/settings/tokens/new?tokenType=read)

Accept the model access terms in the browser, create a read token, then paste it into the installer. Input is hidden.

## 2. Configure the plugin

The easy path is to double-click this file from the repository root:

```text
Install-Windows.cmd
```

It installs the Resolve menu script, writes the config file, bootstraps the local runtime, downloads models, and uses folders next to `Install-Windows.cmd`.

The default folders are:

```text
.\LTX-Video
.\models
.\output
```

If those files are not present yet, the installer prints the exact missing paths and exits cleanly. It does not reuse stale paths from an older config.

Manual equivalent from this repository:

```powershell
.\scripts\install_windows.ps1
```

Advanced custom folders:

```powershell
.\scripts\install_windows.ps1 -CustomPaths
```

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
