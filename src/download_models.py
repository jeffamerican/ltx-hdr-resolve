#!/usr/bin/env python3
"""Download LTX HDR model files into a local models folder."""

import argparse
import os
import sys
import urllib.error
import urllib.request
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


def format_size(num_bytes):
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024


def direct_download(repo_id, filename, output_dir, token):
    url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
    target = output_dir / filename
    part = output_dir / (filename + ".part")

    headers = {"User-Agent": "ltx-hdr-resolve-installer"}
    if token:
        headers["Authorization"] = "Bearer " + token.strip()

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            total = int(response.headers.get("Content-Length") or "0")
            downloaded = 0
            with open(part, "wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        percent = downloaded / total * 100
                        print(
                            f"\r  {format_size(downloaded)} / {format_size(total)} ({percent:.1f}%)",
                            end="",
                            flush=True,
                        )
                    else:
                        print(f"\r  {format_size(downloaded)}", end="", flush=True)
            print()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        detail = body[:1000].replace("\n", " ")
        raise RuntimeError(f"HTTP {exc.code} downloading {repo_id}/{filename}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error downloading {repo_id}/{filename}: {exc}") from exc

    if part.stat().st_size < 1024 * 1024:
        raise RuntimeError(f"Downloaded file is unexpectedly small: {part}")

    part.replace(target)
    return target


def download_models(output_dir, token):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for repo_id, filename in MODEL_FILES:
        target = output_dir / filename
        if target.exists() and target.stat().st_size > 1024 * 1024:
            print("OK: already downloaded " + str(target))
            continue

        print("Downloading " + repo_id + "/" + filename)
        try:
            direct_download(repo_id, filename, output_dir, token)
        except RuntimeError as exc:
            print("ERROR: " + str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        print("OK: downloaded " + str(target))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download LTX HDR model files.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--token", default=os.environ.get("HF_TOKEN", ""))
    args = parser.parse_args(argv)
    download_models(args.output_dir, args.token)


if __name__ == "__main__":
    main()
