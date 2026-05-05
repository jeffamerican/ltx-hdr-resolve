# Windows Setup

The default Windows setup uses the LTX cloud HDR endpoint. It does not download the large open-source model files or require a local high-VRAM GPU.

## 1. Install

Double-click this file from the repository root:

```text
Install-Windows.cmd
```

The installer:

- installs the Resolve menu script
- installs `uv` if needed
- creates a small `.cloud-venv` Python runtime
- asks for an LTX API key
- writes `%USERPROFILE%\.ltx-hdr-resolve\config.json`
- saves the key in `%USERPROFILE%\.ltx-hdr-resolve\secrets.json`

To change the saved API key later:

```text
Set-LTX-Api-Key.cmd
```

Cloud mode still writes local EXR outputs, so keep at least 10 GB free for first tests.

## 2. Config

The default config uses:

```text
mode = ltx_cloud
cloud_upload_limit_mb = 100
cloud_poll_seconds = 5
cloud_timeout_seconds = 1800
```

The current v1 exports a single selected timeline clip when Resolve exposes timeline selection, otherwise the timeline clip under the playhead, and sends that rendered segment to LTX. It only sends a Media Pool source clip when no timeline clip is active and exactly one Media Pool clip is selected. If the rendered segment is larger than the configured upload limit, trim the timeline clip or raise `cloud_upload_limit_mb` only if your LTX plan supports larger uploads.

Advanced users can still install local GPU mode:

```powershell
.\scripts\install_windows.ps1 -Mode Local
```

Local mode downloads model files and can exceed 120 GB.

## 3. Diagnose

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

## 4. Resolve

Restart Resolve after installation. The command appears under:

```text
Workspace -> Scripts -> Utility -> LTX HDR Convert Current Clip
```

Resolve scans these Windows script folders on startup:

- Current user: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility`
- All users: `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility`
