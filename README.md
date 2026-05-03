# LTX HDR Resolve v1

![LTX HDR Resolve](assets/readme/hero.png)

Local-first DaVinci Resolve integration for LTX HDR IC-LoRA.

This v1 is intentionally organized as a Resolve menu script plus an external local worker:

- Resolve script: runs inside DaVinci Resolve, finds the current timeline clip, calls the worker, imports the generated EXR sequence, and adds it as a take.
- Local worker: runs in the user's normal Python environment, validates the LTX checkout and model paths, then executes LTX's `run_hdr_ic_lora.py`.
- Config: lives in `~/.ltx-hdr-resolve/config.json` so model weights, output folders, and the LTX repo stay local to the machine.

## Why this shape

LTX HDR is not a lightweight color transform. It converts SDR video into HDR EXR frames using a large local model pipeline. Keeping that work outside Resolve avoids loading PyTorch into Resolve's scripting interpreter and makes GPU/runtime failures easier to diagnose.

## Requirements

- DaVinci Resolve or Resolve Studio with scripting enabled.
- Python 3.11 runtime for LTX.
- `uv` for setting up the LTX repo environment.
- NVIDIA GPU with enough VRAM for the LTX HDR workflow.
- Local copies of the LTX model files:
  - `ltx-2.3-22b-distilled.safetensors`
  - `ltx-2.3-spatial-upscaler-x2-1.1.safetensors`
  - `ltx-2.3-22b-ic-lora-hdr-0.9.safetensors`
  - `ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors`

## Install

For Windows, use the dedicated guide: [docs/windows-setup.md](docs/windows-setup.md).

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
4. The worker processes the source media locally.
5. Resolve imports the generated EXR sequence into an `LTX HDR` bin and adds it as a take on the current timeline item when supported by the host API.

## Current v1 behavior

- Processes the current timeline clip's source file, not only the timeline-trimmed range.
- Imports the generated EXR sequence as one media-pool item.
- Adds the EXR media as a take on the current clip when Resolve accepts it.
- Writes job manifests and logs under the configured output directory.
- Does not download models automatically.
- Does not change project color-management settings automatically yet.

## Windows quick start

```powershell
git clone https://github.com/jeffamerican/ltx-hdr-resolve.git
cd ltx-hdr-resolve
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ltx-hdr-resolve"
Copy-Item .\config\config.example.windows.json "$env:USERPROFILE\.ltx-hdr-resolve\config.json"
notepad "$env:USERPROFILE\.ltx-hdr-resolve\config.json"
.\scripts\diagnose_local_runtime.ps1
.\scripts\install_resolve_script.ps1
```

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
