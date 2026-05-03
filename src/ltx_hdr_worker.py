#!/usr/bin/env python3
"""Local worker for LTX HDR Resolve v1."""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path


REQUIRED_CONFIG_KEYS = (
    "ltx_repo_path",
    "ltx_python",
    "ltx_hdr_script",
    "output_root",
    "distilled_checkpoint",
    "upscaler",
    "lora",
    "text_embeddings",
)


def load_config(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        config = json.load(handle)
    return config


def sanitize_name(value):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "clip").strip("._")
    return safe or "clip"


def resolve_script_path(config):
    script = Path(config["ltx_hdr_script"])
    if script.is_absolute():
        return script
    return Path(config["ltx_repo_path"]) / script


def validate_config(config):
    errors = []
    for key in REQUIRED_CONFIG_KEYS:
        if not config.get(key):
            errors.append("Missing config key: " + key)

    path_keys = (
        "ltx_repo_path",
        "ltx_python",
        "distilled_checkpoint",
        "upscaler",
        "lora",
        "text_embeddings",
    )
    for key in path_keys:
        value = config.get(key)
        if value and not Path(value).exists():
            errors.append(key + " does not exist: " + value)

    script = resolve_script_path(config) if config.get("ltx_hdr_script") and config.get("ltx_repo_path") else None
    if script and not script.exists():
        errors.append("ltx_hdr_script does not exist: " + str(script))

    max_frames = config.get("max_frames")
    if max_frames is not None:
        try:
            max_frames_int = int(max_frames)
            if (max_frames_int - 1) % 8 != 0:
                errors.append("max_frames must satisfy (N - 1) % 8 == 0.")
        except ValueError:
            errors.append("max_frames must be an integer.")

    if config.get("no_save_exr"):
        errors.append("no_save_exr cannot be true for Resolve import jobs.")

    return errors


def build_ltx_command(config, input_path, output_dir):
    script_path = resolve_script_path(config)
    if script_path.name == "hdr_ic_lora.py":
        raise RuntimeError(
            "The current LTX-2 repository exposes HDR as a Python pipeline, not the old "
            "run_hdr_ic_lora.py command-line script. The local runtime is installed, but "
            "conversion needs the plugin wrapper implementation."
        )

    command = [
        config["ltx_python"],
        str(script_path),
        "--input",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--distilled-checkpoint",
        config["distilled_checkpoint"],
        "--upscaler",
        config["upscaler"],
        "--lora",
        config["lora"],
        "--text-embeddings",
        config["text_embeddings"],
    ]

    if config.get("exr_half", True):
        command.append("--exr-half")
    if config.get("high_quality", True):
        command.append("--high-quality")
    if config.get("skip_mp4"):
        command.append("--skip-mp4")
    if config.get("no_save_exr"):
        command.append("--no-save-exr")
    if config.get("seed") is not None:
        command.extend(["--seed", str(config["seed"])])
    if config.get("max_frames") is not None:
        command.extend(["--max-frames", str(config["max_frames"])])

    return command


def find_outputs(input_path, output_dir):
    stem = Path(input_path).stem
    expected_exr = Path(output_dir) / (stem + "_exr")
    exr_dirs = []
    if expected_exr.is_dir():
        exr_dirs.append(expected_exr)
    exr_dirs.extend(path for path in Path(output_dir).glob("*_exr") if path.is_dir() and path not in exr_dirs)

    mp4s = list(Path(output_dir).glob("*.mp4"))
    return {
        "exr_dir": str(exr_dirs[0]) if exr_dirs else "",
        "preview_mp4": str(mp4s[0]) if mp4s else "",
        "exr_frame_count": len(list(exr_dirs[0].glob("*.exr"))) if exr_dirs else 0,
    }


def write_manifest(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    return path


def diagnose(args):
    config = load_config(args.config)
    errors = validate_config(config)
    if errors:
        for error in errors:
            print("ERROR: " + error)
        return 1

    print("OK: config is valid")
    print("LTX repo: " + config["ltx_repo_path"])
    print("LTX python: " + config["ltx_python"])
    print("LTX HDR script: " + str(resolve_script_path(config)))
    print("Output root: " + config["output_root"])
    return 0


def convert(args):
    config = load_config(args.config)
    errors = validate_config(config)
    input_path = Path(args.input)
    if not input_path.exists():
        errors.append("input does not exist: " + str(input_path))
    if errors:
        for error in errors:
            print("ERROR: " + error, file=sys.stderr)
        return 2

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    clip_name = sanitize_name(args.clip_name or input_path.stem)
    job_dir = Path(config["output_root"]) / (timestamp + "_" + clip_name)
    output_dir = job_dir / "ltx_output"
    log_path = job_dir / "ltx_hdr.log"
    manifest_path = job_dir / "manifest.json"
    output_dir.mkdir(parents=True, exist_ok=True)

    command = build_ltx_command(config, input_path, output_dir)
    env = os.environ.copy()
    env["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    env.update({str(k): str(v) for k, v in config.get("extra_env", {}).items()})

    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    with open(log_path, "w") as log:
        log.write("Command:\n")
        log.write(json.dumps(command, indent=2))
        log.write("\n\n")
        log.flush()
        completed = subprocess.run(
            command,
            cwd=config["ltx_repo_path"],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )

    outputs = find_outputs(input_path, output_dir)
    status = "completed" if completed.returncode == 0 and outputs["exr_dir"] else "failed"
    manifest = {
        "status": status,
        "started_at": started_at,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "returncode": completed.returncode,
        "input": str(input_path),
        "clip_name": args.clip_name,
        "job_dir": str(job_dir),
        "output_dir": str(output_dir),
        "log_path": str(log_path),
        "command": command,
        **outputs,
    }
    write_manifest(manifest_path, manifest)

    if status != "completed":
        print("LTX HDR conversion failed. See log: " + str(log_path), file=sys.stderr)
        print(str(manifest_path))
        return 3

    print(str(manifest_path))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Local LTX HDR worker for Resolve.")
    subparsers = parser.add_subparsers(dest="command")

    diagnose_parser = subparsers.add_parser("diagnose", help="Validate local LTX HDR configuration.")
    diagnose_parser.add_argument("--config", required=True)
    diagnose_parser.set_defaults(func=diagnose)

    convert_parser = subparsers.add_parser("convert", help="Convert one source video through local LTX HDR.")
    convert_parser.add_argument("--config", required=True)
    convert_parser.add_argument("--input", required=True)
    convert_parser.add_argument("--clip-name", default="")
    convert_parser.set_defaults(func=convert)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
