#!/usr/bin/env python3
"""Local worker for LTX HDR Resolve v1."""

import argparse
import datetime as dt
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


MANIFEST_MARKER = "LTX_HDR_MANIFEST="
LOG_MARKER = "LTX_HDR_LOG="
STATUS_MARKER = "LTX_HDR_STATUS="
PROGRESS_INTERVAL_SECONDS = 10
WINDOWS_EXIT_CODES = {
    0xC0000005: "Windows native access violation (0xC0000005)",
    0xC000001D: "Windows illegal instruction crash (0xC000001D)",
    0xC0000135: "Windows missing DLL crash (0xC0000135)",
    0xC000007B: "Windows invalid image/DLL architecture crash (0xC000007B)",
    0xC0000409: "Windows stack buffer overrun crash (0xC0000409)",
}
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


def ltx_package_paths(config):
    repo = Path(config["ltx_repo_path"])
    paths = []
    for package in ("ltx-core", "ltx-pipelines", "ltx-trainer"):
        src = repo / "packages" / package / "src"
        if src.exists():
            paths.append(str(src))
    return paths


def build_ltx_command(config, input_path, output_dir):
    script_path = resolve_script_path(config)
    if script_path.name == "hdr_ic_lora.py":
        command = [
            config["ltx_python"],
            "-m",
            "ltx_pipelines.hdr_ic_lora",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--distilled-checkpoint-path",
            config["distilled_checkpoint"],
            "--spatial-upsampler-path",
            config["upscaler"],
            "--hdr-lora",
            config["lora"],
            "--text-embeddings",
            config["text_embeddings"],
        ]
    else:
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
    if config.get("high_quality", False):
        command.append("--high-quality")
    if config.get("skip_mp4"):
        command.append("--skip-mp4")
    if config.get("no_save_exr") and script_path.name != "hdr_ic_lora.py":
        command.append("--no-save-exr")
    if config.get("seed") is not None:
        command.extend(["--seed", str(config["seed"])])
    if config.get("max_frames") is not None:
        frame_flag = "--num-frames" if script_path.name == "hdr_ic_lora.py" else "--max-frames"
        command.extend([frame_flag, str(config["max_frames"])])
    if script_path.name == "hdr_ic_lora.py" and config.get("spatial_tile") is not None:
        command.extend(["--spatial-tile", str(config["spatial_tile"])])
    if script_path.name == "hdr_ic_lora.py" and config.get("offload"):
        command.extend(["--offload", str(config["offload"])])

    return command


def describe_returncode(returncode):
    if returncode == 0:
        return "completed successfully"
    if os.name == "nt" or returncode > 255 or returncode < 0:
        unsigned = returncode & 0xFFFFFFFF
        reason = WINDOWS_EXIT_CODES.get(unsigned)
        if reason:
            return reason + ". A native dependency crashed before Python could raise an exception. This is commonly caused by CUDA/PyTorch/video-driver memory pressure or an incompatible native runtime."
        return "Windows native process exit 0x%08X (%d)" % (unsigned, returncode)
    return "process exit code " + str(returncode)


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


def run_ltx_command(command, cwd, env, log_path):
    emit_status("Launching LTX HDR pipeline")
    emit_status("EXR frames are usually written near the end; long GPU-only sections can be quiet.")
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("Command:\n")
        log.write(json.dumps(command, indent=2))
        log.write("\n\n")
        log.flush()

        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            **startup_kwargs()
        )

        line_queue = queue.Queue()
        if process.stdout:
            reader = threading.Thread(target=read_process_lines, args=(process.stdout, line_queue))
            reader.daemon = True
            reader.start()
        else:
            line_queue.put(None)

        started = time.monotonic()
        last_update = time.monotonic()
        latest_line = ""
        while True:
            try:
                line = line_queue.get(timeout=1)
            except queue.Empty:
                now = time.monotonic()
                if now - last_update >= PROGRESS_INTERVAL_SECONDS:
                    message = "Still running after " + format_elapsed(now - started)
                    if latest_line:
                        message += ". Latest LTX log: " + latest_line[-220:]
                    else:
                        message += ". Waiting for first LTX log line."
                    emit_status(message)
                    last_update = now
                continue

            if line is None:
                break

            log.write(line)
            log.flush()
            cleaned = line.strip()
            if not cleaned:
                continue
            latest_line = cleaned
            now = time.monotonic()
            if should_forward_ltx_line(cleaned) or now - last_update >= PROGRESS_INTERVAL_SECONDS:
                emit_status(cleaned[-300:])
                last_update = now

        returncode = process.wait()
        if returncode == 0:
            emit_status("LTX HDR pipeline finished; checking generated EXR output")
        else:
            message = "LTX HDR pipeline exited: " + describe_returncode(returncode)
            if latest_line:
                message += ". Latest log: " + latest_line[-220:]
            emit_status(message)
        return returncode


def write_manifest(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    return path


def emit_manifest(path):
    print(MANIFEST_MARKER + str(path), flush=True)


def emit_log(path):
    print(LOG_MARKER + str(path), flush=True)


def emit_status(message):
    print(STATUS_MARKER + str(message).replace("\r", " ").replace("\n", " ").strip(), flush=True)


def startup_kwargs():
    if os.name != "nt":
        return {}

    kwargs = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    except Exception:
        pass
    return kwargs


def should_forward_ltx_line(line):
    lowered = line.lower()
    interesting = (
        "found ",
        "loading",
        "pipeline",
        "generating",
        "encoding",
        "waiting",
        "all inference",
        "total wall time",
        "error",
        "failed",
        "traceback",
        "%|",
    )
    return any(token in lowered for token in interesting)


def format_elapsed(seconds):
    seconds = max(0, int(seconds))
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return "%dh %02dm %02ds" % (hours, minutes, remainder)
    return "%dm %02ds" % (minutes, remainder)


def read_process_lines(stream, line_queue):
    try:
        for line in stream:
            line_queue.put(line)
    finally:
        line_queue.put(None)


def make_job_paths(args, config=None):
    input_path = Path(args.input)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    clip_name = sanitize_name(args.clip_name or input_path.stem)
    output_root = ""
    if config:
        output_root = config.get("output_root") or ""
    if output_root:
        root = Path(output_root)
    else:
        root = Path(tempfile.gettempdir()) / "ltx-hdr-resolve"
    job_dir = root / (timestamp + "_" + clip_name)
    output_dir = job_dir / "ltx_output"
    log_path = job_dir / "ltx_hdr.log"
    manifest_path = job_dir / "manifest.json"
    return job_dir, output_dir, log_path, manifest_path


def write_failure_manifest(args, config, returncode, error, status="failed", errors=None, command=None, job_paths=None):
    if job_paths:
        job_dir, output_dir, log_path, manifest_path = job_paths
    else:
        job_dir, output_dir, log_path, manifest_path = make_job_paths(args, config)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest = {
        "status": status,
        "started_at": now,
        "finished_at": now,
        "returncode": returncode,
        "input": str(Path(args.input)),
        "clip_name": args.clip_name,
        "job_dir": str(job_dir),
        "output_dir": str(output_dir),
        "log_path": str(log_path),
        "error": error,
        "errors": errors or [],
        "exr_dir": "",
        "preview_mp4": "",
        "exr_frame_count": 0,
    }
    if command:
        manifest["command"] = command
    write_manifest(manifest_path, manifest)
    emit_manifest(manifest_path)
    return manifest_path


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
    try:
        config = load_config(args.config)
    except Exception as exc:
        message = "Could not load config: " + str(exc)
        print("ERROR: " + message, file=sys.stderr)
        write_failure_manifest(args, None, 2, message, errors=[message])
        return 2

    errors = validate_config(config)
    input_path = Path(args.input)
    if not input_path.exists():
        errors.append("input does not exist: " + str(input_path))
    if errors:
        for error in errors:
            print("ERROR: " + error, file=sys.stderr)
        write_failure_manifest(args, config, 2, "\n".join(errors), errors=errors)
        return 2

    job_dir, output_dir, log_path, manifest_path = make_job_paths(args, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    emit_log(log_path)
    emit_status("Job folder: " + str(job_dir))
    frame_count = int(config.get("max_frames") or 161)
    if config.get("high_quality", False):
        emit_status("Configured for " + str(frame_count) + " output frames; high-quality mode expands this to " + str(2 * frame_count - 1) + " internal frames.")
    else:
        emit_status("Configured for " + str(frame_count) + " output frames.")
    if config.get("skip_mp4"):
        emit_status("MP4 preview encoding is disabled; Resolve will import the generated EXR sequence.")
    if config.get("spatial_tile") is not None:
        emit_status("Using spatial tile " + str(config.get("spatial_tile")) + " to reduce GPU memory pressure without changing output resolution.")
    if config.get("offload"):
        emit_status("Using LTX offload mode: " + str(config.get("offload")) + ". This preserves quality but can be slower.")

    try:
        command = build_ltx_command(config, input_path, output_dir)
    except Exception as exc:
        status = "unsupported" if isinstance(exc, RuntimeError) else "failed"
        returncode = 4 if status == "unsupported" else 3
        if status == "unsupported":
            print("LTX HDR conversion is not available for the installed LTX-2 pipeline yet.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        write_failure_manifest(args, config, returncode, str(exc), status=status, job_paths=(job_dir, output_dir, log_path, manifest_path))
        return returncode

    env = os.environ.copy()
    env["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    package_paths = ltx_package_paths(config)
    if package_paths:
        existing_pythonpath = env.get("PYTHONPATH", "")
        if existing_pythonpath:
            package_paths.append(existing_pythonpath)
        env["PYTHONPATH"] = os.pathsep.join(package_paths)
    env.update({str(k): str(v) for k, v in config.get("extra_env", {}).items()})

    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        returncode = run_ltx_command(command, config["ltx_repo_path"], env, log_path)
    except Exception as exc:
        message = "Could not run LTX HDR command: " + str(exc)
        print(message, file=sys.stderr)
        write_failure_manifest(args, config, 3, message, command=command, job_paths=(job_dir, output_dir, log_path, manifest_path))
        return 3

    outputs = find_outputs(input_path, output_dir)
    status = "completed" if returncode == 0 and outputs["exr_dir"] else "failed"
    manifest = {
        "status": status,
        "started_at": started_at,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "returncode": returncode,
        "input": str(input_path),
        "clip_name": args.clip_name,
        "job_dir": str(job_dir),
        "output_dir": str(output_dir),
        "log_path": str(log_path),
        "command": command,
        **outputs,
    }
    if status != "completed":
        manifest["returncode_detail"] = describe_returncode(returncode)
        if returncode == 0:
            manifest["error"] = "LTX command finished, but no EXR output directory was found."
        else:
            manifest["error"] = "LTX command failed: " + describe_returncode(returncode) + "."
    write_manifest(manifest_path, manifest)

    if status != "completed":
        print("LTX HDR conversion failed. See log: " + str(log_path), file=sys.stderr)
        emit_manifest(manifest_path)
        return 3

    emit_manifest(manifest_path)
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
