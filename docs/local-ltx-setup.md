# Local LTX Setup

Use this when preparing a workstation for the Resolve plugin.

## 1. Clone LTX

```bash
git clone https://github.com/Lightricks/LTX-2.git LTX-Video
cd LTX-Video
```

## 2. Create the Python 3.11 environment

The HDR script guide uses `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e packages/ltx-core -e packages/ltx-pipelines -e packages/ltx-trainer
```

## 3. Download model files

Download these files from the LTX 2.3 Hugging Face collection and keep them in a local model directory:

- `ltx-2.3-22b-distilled-1.1.safetensors`
- `ltx-2.3-spatial-upscaler-x2-1.1.safetensors`
- `ltx-2.3-22b-ic-lora-hdr-0.9.safetensors`
- `ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors`

## 4. Configure the Resolve bridge

```bash
mkdir -p ~/.ltx-hdr-resolve
cp config/config.example.json ~/.ltx-hdr-resolve/config.json
```

Edit `~/.ltx-hdr-resolve/config.json`:

- `ltx_repo_path`: local `LTX-Video` checkout.
- `ltx_python`: usually `LTX-Video/.venv/bin/python`.
- `ltx_hdr_script`: usually `packages/ltx-pipelines/src/ltx_pipelines/hdr_ic_lora.py`.
- `output_root`: local folder for job logs, MP4 previews, and EXR frames.
- model paths: absolute paths to the four downloaded files.

Then run:

```bash
./scripts/diagnose_local_runtime.sh
```

## 5. Verify LTX outside Resolve first

Run the worker against a short SDR test clip before using Resolve:

```bash
python3 src/ltx_hdr_worker.py convert \
  --config ~/.ltx-hdr-resolve/config.json \
  --input /path/to/short-test-clip.mp4 \
  --clip-name short-test
```

The command prints a `manifest.json` path. Check that it reports `status: completed` and points to a directory with EXR frames.
