# macOS Setup

The macOS installer uses LTX cloud mode by default. It does not download local LTX model files.

## 1. Install

Download or clone this repository, then double-click:

```text
Install-macOS.command
```

macOS may ask for permission to run a downloaded script. If needed, right-click the file and choose `Open`.

The installer:

- Installs the DaVinci Resolve menu scripts.
- Creates `.cloud-venv` inside the `ltx-hdr-resolve` folder.
- Opens the LTX API key page and asks for your key.
- Writes `~/.ltx-hdr-resolve/config.json`.
- Saves the key in `~/.ltx-hdr-resolve/secrets.json`.
- Uses `output` inside the `ltx-hdr-resolve` folder for generated jobs, logs, and EXR frames.

Cloud mode still writes local EXR outputs, so keep at least 10 GB free for first tests.

## 2. Change API Key

Double-click:

```text
Set-LTX-Api-Key-macOS.command
```

## 3. Resolve

Restart Resolve after installation. The command appears under:

```text
Workspace -> Scripts -> Utility -> LTX HDR Convert Current Clip
```

Resolve scans this macOS script folder on startup:

```text
~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility
```

## Advanced

To choose a different output folder:

```bash
./scripts/install_macos.sh --custom-paths
```

For local GPU mode, use [local-ltx-setup.md](local-ltx-setup.md). The one-click macOS installer is cloud-only for v1.
