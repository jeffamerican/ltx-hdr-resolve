#!/usr/bin/env python3
"""Download LTX HDR model files into a local models folder."""

import argparse
import os
from pathlib import Path


MODEL_FILES = (
    (
        "Lightricks/LTX-2.3",
        "ltx-2.3-22b-distilled-1.1.safetensors",
    ),
    (
        "Lightricks/LTX-2.3",
        "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
    ),
    (
        "Lightricks/LTX-2.3-22b-IC-LoRA-HDR",
        "ltx-2.3-22b-ic-lora-hdr-0.9.safetensors",
    ),
    (
        "Lightricks/LTX-2.3-22b-IC-LoRA-HDR",
        "ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors",
    ),
)


def download_models(output_dir, token):
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise SystemExit("huggingface_hub is not installed in the LTX Python environment.") from exc

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for repo_id, filename in MODEL_FILES:
        target = output_dir / filename
        if target.exists() and target.stat().st_size > 1024 * 1024:
            print("OK: already downloaded " + str(target))
            continue

        print("Downloading " + repo_id + "/" + filename)
        hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(output_dir),
            local_dir_use_symlinks=False,
            token=token or None,
            resume_download=True,
        )
        print("OK: downloaded " + str(target))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download LTX HDR model files.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--token", default=os.environ.get("HF_TOKEN", ""))
    args = parser.parse_args(argv)
    download_models(args.output_dir, args.token)


if __name__ == "__main__":
    main()
