# LTX HDR Resolve v1

![LTX HDR Resolve](assets/readme/hero.png)

DaVinci Resolve integration for LTX HDR IC-LoRA, with LTX cloud mode as the default path and local GPU mode available for advanced users.

## Windows Install

For Windows users, the install path is:

```text
1. Download or clone this repository.
2. Double-click Install-Windows.cmd.
3. Restart DaVinci Resolve.
```

The installer file is at the repository root:

```text
Install-Windows.cmd
```

It installs the Resolve menu script, creates a small Python runtime, asks for an LTX API key, writes `%USERPROFILE%\.ltx-hdr-resolve\config.json`, and stores the key in `%USERPROFILE%\.ltx-hdr-resolve\secrets.json`.

To change the saved LTX API key later, double-click:

```text
Set-LTX-Api-Key.cmd
```

**Disk space warning:** cloud mode does not download the large LTX model files, but EXR outputs can still be large. Keep at least **10 GB free** for first tests. Local GPU mode can exceed **120 GB** because it downloads models and Python package caches.

By default, it keeps everything inside the cloned `ltx-hdr-resolve` folder:

```text
ltx-hdr-resolve\
  .cloud-venv\ # small Python runtime for the Resolve worker
  output\      # generated jobs, logs, previews, EXR frames
```

The Windows installer writes `mode=ltx_cloud` by default. Advanced users can install local GPU mode with:

```powershell
.\scripts\install_windows.ps1 -Mode Local
```

After restarting Resolve, run:

```text
Workspace -> Scripts -> Utility -> LTX HDR Convert Current Clip
```

Advanced users can run `.\scripts\install_windows.ps1 -CustomPaths` to choose different folders.

## What This Does

This v1 is intentionally organized as a Resolve menu script plus an external local worker:

- Resolve script: runs inside DaVinci Resolve, exports the current timeline clip range, auto-segments it if needed for LTX cloud limits, calls the worker, imports the generated EXR sequence, and adds it as a take when the result is a single segment.
- Worker: runs outside Resolve, uploads the current clip to the LTX cloud HDR endpoint, downloads the EXR ZIP, and writes a manifest.
- Config: lives in `~/.ltx-hdr-resolve/config.json`. The LTX API key lives separately in `~/.ltx-hdr-resolve/secrets.json`.

## Why this shape

LTX HDR is not a lightweight color transform. Cloud mode avoids requiring a local 48-80 GB GPU while keeping Resolve focused on coordination and import.

## Requirements

- DaVinci Resolve or Resolve Studio with scripting enabled.
- LTX API key for cloud mode.
- `uv` for creating the worker Python runtime.
- Enough disk space for downloaded EXR outputs.

## macOS / Manual Install

1. Copy the config template:

   ```bash
   mkdir -p ~/.ltx-hdr-resolve
   cp config/config.example.json ~/.ltx-hdr-resolve/config.json
   ```

2. Edit `~/.ltx-hdr-resolve/config.json` and point it at your LTX repo, venv Python, model files, and output folder.

3. Run the diagnostic:

   ```bash
   python3 src/ltx_hdr_worker.py diagnose --config ~/.ltx-hdr-resolve/config.json
   ```

   See [docs/local-ltx-setup.md](docs/local-ltx-setup.md) for the full local workstation setup.

4. Install the Resolve script:

   ```bash
   ./scripts/install_resolve_script.sh
   ```

5. Restart Resolve. The menu item appears under:

   ```text
   Workspace -> Scripts -> Utility -> LTX HDR Convert Current Clip
   ```

## Use

1. Open the timeline in Resolve.
2. Move the playhead onto the clip you want to convert.
3. Run `Workspace -> Scripts -> Utility -> LTX HDR Convert Current Clip`.
4. Resolve exports only that timeline clip range, auto-segments it when needed, then the worker uploads each segment to LTX cloud, polls the jobs, downloads EXRs, and writes logs.
5. Resolve imports the generated EXR sequence into an `LTX HDR` bin and adds it as a take on the current timeline item when supported by the host API.

## Current v1 behavior

- Processes a single selected timeline clip when Resolve exposes timeline selection, otherwise the timeline clip under the playhead. It only uses a Media Pool source clip when no timeline clip is active and exactly one Media Pool clip is selected.
- Auto-segments timeline clips that exceed LTX cloud frame limits. Single-segment results are added as a take; multi-segment results are imported as separate EXR sequences in the `LTX HDR` bin.
- Imports the generated EXR sequence as one media-pool item.
- Adds the EXR media as a take on the current clip when Resolve accepts it.
- Prints worker progress in the Resolve console and writes job manifests/logs under the configured output directory.
- Uses LTX cloud mode by default on Windows.
- Local GPU mode remains available with `.\scripts\install_windows.ps1 -Mode Local`.
- Does not change project color-management settings automatically yet.

## Recommended Resolve color settings

For imported HDR EXR files, use the LTX-recommended Resolve settings:

- Color science: `ACEScct`
- ACES version: `ACES 2.0`
- ACES Input Transform: `sRGB (Linear) - CSC`
- ACES Output Transform: `Rec.2100 ST.2084 (1000 nit)`

Also enable 10-bit precision in viewers if available.

## Next steps after v1

- Timeline-range export before LTX processing.
- Workflow Integration panel for queue/progress/config.
- Project color-management checker with user confirmation.
- Optional side-by-side tonemapped preview import.
- Platform-specific installer zips.
