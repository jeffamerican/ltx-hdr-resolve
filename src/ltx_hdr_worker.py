#!/usr/bin/env python3
"""Local worker for LTX HDR Resolve v1."""

import argparse
import datetime as dt
import json
import mimetypes
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


MANIFEST_MARKER = "LTX_HDR_MANIFEST="
LOG_MARKER = "LTX_HDR_LOG="
STATUS_MARKER = "LTX_HDR_STATUS="
PROGRESS_INTERVAL_SECONDS = 10
LTX_API_BASE_URL = "https://api.ltx.video"
DEFAULT_CLOUD_POLL_SECONDS = 5
DEFAULT_CLOUD_TIMEOUT_SECONDS = 1800
DEFAULT_CLOUD_UPLOAD_LIMIT_MB = 100
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
LOCAL_REQUIRED_CONFIG_KEYS = REQUIRED_CONFIG_KEYS
CLOUD_REQUIRED_CONFIG_KEYS = (
    "output_root",
    "ltx_python",
)


def load_config(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        config = json.load(handle)
    return config


def sanitize_name(value):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "clip").strip("._")
    return safe or "clip"


def run_mode(config):
    return str(config.get("mode") or "local").lower().strip()


def resolve_script_path(config):
    script = Path(config["ltx_hdr_script"])
    if script.is_absolute():
        return script
    return Path(config["ltx_repo_path"]) / script


def validate_config(config):
    errors = []
    mode = run_mode(config)
    required_keys = CLOUD_REQUIRED_CONFIG_KEYS if mode == "ltx_cloud" else LOCAL_REQUIRED_CONFIG_KEYS
    for key in required_keys:
        if not config.get(key):
            errors.append("Missing config key: " + key)

    path_keys = ("ltx_python",)
    if mode != "ltx_cloud":
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

    if mode != "ltx_cloud":
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


def default_secrets_path():
    return Path.home() / ".ltx-hdr-resolve" / "secrets.json"


def load_ltx_api_key(config):
    env_key = (os.environ.get("LTX_API_KEY") or os.environ.get("LTXV_API_KEY") or "").strip()
    if env_key:
        return env_key

    config_key = str(config.get("ltx_api_key") or "").strip()
    if config_key:
        return config_key

    secrets_path = Path(config.get("cloud_api_key_path") or default_secrets_path())
    if secrets_path.exists():
        with open(secrets_path, "r", encoding="utf-8-sig") as handle:
            secrets = json.load(handle)
        key = str(secrets.get("ltx_api_key") or "").strip()
        if key:
            return key

    raise RuntimeError(
        "Missing LTX API key. Run Set-LTX-Api-Key.cmd or set LTX_API_KEY, then try again."
    )


def ltx_api_headers(api_key, content_type="application/json"):
    headers = {"Authorization": "Bearer " + api_key}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def ltx_request_json(method, url, api_key, payload=None, extra_headers=None):
    body = None
    headers = ltx_api_headers(api_key)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError("LTX API HTTP " + str(exc.code) + ": " + detail[:1000]) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not reach LTX API: " + str(exc)) from exc

    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def first_present(mapping, names, default=""):
    for name in names:
        value = mapping.get(name)
        if value:
            return value
    return default


def create_ltx_upload(api_key, file_path):
    file_name = Path(file_path).name
    content_type = mimetypes.guess_type(file_name)[0] or "video/mp4"
    data = ltx_request_json("POST", LTX_API_BASE_URL + "/v1/upload", api_key)
    upload_url = first_present(data, ("upload_url", "uploadUrl", "url", "signed_url", "signedUrl"))
    storage_uri = first_present(data, ("storage_uri", "storageUri", "file_url", "fileUrl", "uri"))
    required_headers = data.get("required_headers") or data.get("requiredHeaders") or {}
    if not upload_url:
        raise RuntimeError("LTX upload response did not include an upload URL.")
    if not storage_uri:
        raise RuntimeError("LTX upload response did not include a storage URI.")
    return upload_url, storage_uri, content_type, required_headers


def upload_file_to_signed_url(upload_url, file_path, content_type, required_headers):
    headers = {"Content-Type": content_type}
    headers.update({str(k): str(v) for k, v in required_headers.items()})
    with open(file_path, "rb") as handle:
        request = urllib.request.Request(upload_url, data=handle.read(), headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError("LTX upload HTTP " + str(exc.code) + ": " + detail[:1000]) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not upload video to LTX: " + str(exc)) from exc


def cloud_job_status(data):
    return str(first_present(data, ("status", "state", "job_status", "jobStatus"), "")).lower()


def cloud_job_id(data):
    return str(first_present(data, ("id", "job_id", "jobId", "request_id", "requestId"), ""))


def submit_ltx_hdr_job(config, api_key, storage_uri):
    payload = {
        "video_uri": storage_uri,
    }
    if config.get("seed") is not None:
        payload["seed"] = int(config["seed"])
    data = ltx_request_json("POST", LTX_API_BASE_URL + "/v2/video-to-video-hdr", api_key, payload)
    job_id = cloud_job_id(data)
    if not job_id:
        job_id = first_present(data.get("job", {}) if isinstance(data.get("job"), dict) else {}, ("id", "job_id", "jobId"), "")
    if not job_id:
        raise RuntimeError("LTX HDR response did not include a job id.")
    return job_id, data


def poll_ltx_job(config, api_key, job_id):
    poll_seconds = int(config.get("cloud_poll_seconds") or DEFAULT_CLOUD_POLL_SECONDS)
    timeout_seconds = int(config.get("cloud_timeout_seconds") or DEFAULT_CLOUD_TIMEOUT_SECONDS)
    started = time.monotonic()
    status_url = LTX_API_BASE_URL + "/v2/video-to-video-hdr/" + urllib.parse.quote(job_id)
    while True:
        data = ltx_request_json("GET", status_url, api_key)
        status = cloud_job_status(data)
        if status in ("completed", "succeeded", "success", "done"):
            return data
        if status in ("failed", "error", "cancelled", "canceled"):
            raise RuntimeError("LTX HDR job failed: " + json.dumps(data, sort_keys=True)[:1500])
        if time.monotonic() - started > timeout_seconds:
            raise RuntimeError("Timed out waiting for LTX HDR job " + job_id + ".")
        emit_status("LTX cloud job " + job_id + " is " + (status or "running") + " after " + format_elapsed(time.monotonic() - started))
        time.sleep(poll_seconds)


def find_cloud_result_url(job_data):
    candidates = [
        job_data,
        job_data.get("output", {}) if isinstance(job_data.get("output"), dict) else {},
        job_data.get("result", {}) if isinstance(job_data.get("result"), dict) else {},
        job_data.get("data", {}) if isinstance(job_data.get("data"), dict) else {},
    ]
    for candidate in candidates:
        value = first_present(
            candidate,
            ("exr_frames_url", "exrFramesUrl", "exr_zip_url", "exrZipUrl", "url", "output_url", "outputUrl"),
        )
        if value:
            return value
    raise RuntimeError("Completed LTX HDR job did not include an EXR frames URL.")


def safe_extract_zip(zip_path, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            name = member.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            target = destination / Path(name).name
            if Path(name).suffix.lower() != ".exr":
                continue
            with archive.open(member) as source, open(target, "wb") as output:
                output.write(source.read())


def download_cloud_exrs(url, api_key, output_dir, input_path):
    zip_path = Path(output_dir) / (Path(input_path).stem + "_ltx_hdr_exr.zip")
    exr_dir = Path(output_dir) / (Path(input_path).stem + "_exr")
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=600) as response, open(zip_path, "wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError("LTX EXR download HTTP " + str(exc.code) + ": " + detail[:1000]) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not download LTX EXR frames: " + str(exc)) from exc
    safe_extract_zip(zip_path, exr_dir)
    return zip_path, exr_dir


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


def convert_cloud(args, config, input_path, job_paths):
    job_dir, output_dir, log_path, manifest_path = job_paths
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    api_key = load_ltx_api_key(config)
    upload_limit_mb = int(config.get("cloud_upload_limit_mb") or DEFAULT_CLOUD_UPLOAD_LIMIT_MB)
    input_size_mb = input_path.stat().st_size / (1024 * 1024)
    if input_size_mb > upload_limit_mb:
        raise RuntimeError(
            "Input file is %.1f MB, above the configured LTX upload limit of %d MB. "
            "Use a shorter exported clip/segment or raise cloud_upload_limit_mb if your LTX plan supports it."
            % (input_size_mb, upload_limit_mb)
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    emit_status("Running in LTX cloud mode.")
    emit_status("Uploading source clip to LTX (" + ("%.1f" % input_size_mb) + " MB).")
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("Cloud mode: LTX API\n")
        log.write("Input: " + str(input_path) + "\n")
        log.write("Output: " + str(output_dir) + "\n\n")
        log.flush()

        upload_url, storage_uri, content_type, required_headers = create_ltx_upload(api_key, input_path)
        log.write("Upload storage URI: " + storage_uri + "\n")
        log.flush()
        upload_file_to_signed_url(upload_url, input_path, content_type, required_headers)
        emit_status("Upload complete. Submitting LTX HDR cloud job.")

        job_id, submit_response = submit_ltx_hdr_job(config, api_key, storage_uri)
        log.write("Submit response:\n")
        log.write(json.dumps(submit_response, indent=2, sort_keys=True))
        log.write("\n\n")
        log.flush()
        emit_status("Submitted LTX cloud job: " + job_id)

        job_data = poll_ltx_job(config, api_key, job_id)
        log.write("Completed job response:\n")
        log.write(json.dumps(job_data, indent=2, sort_keys=True))
        log.write("\n\n")
        log.flush()

        result_url = find_cloud_result_url(job_data)
        emit_status("Downloading LTX HDR EXR frames.")
        zip_path, exr_dir = download_cloud_exrs(result_url, api_key, output_dir, input_path)
        frame_count = len(list(Path(exr_dir).glob("*.exr")))
        if frame_count < 1:
            raise RuntimeError("LTX cloud job completed, but the downloaded EXR ZIP contained no EXR frames.")

        manifest = {
            "status": "completed",
            "mode": "ltx_cloud",
            "started_at": started_at,
            "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "returncode": 0,
            "input": str(input_path),
            "clip_name": args.clip_name,
            "job_dir": str(job_dir),
            "output_dir": str(output_dir),
            "log_path": str(log_path),
            "ltx_job_id": job_id,
            "exr_zip": str(zip_path),
            "exr_dir": str(exr_dir),
            "preview_mp4": "",
            "exr_frame_count": frame_count,
        }
        write_manifest(manifest_path, manifest)
        emit_status("Downloaded " + str(frame_count) + " EXR frames from LTX cloud.")
        emit_manifest(manifest_path)
        return 0


def diagnose(args):
    config = load_config(args.config)
    errors = validate_config(config)
    if errors:
        for error in errors:
            print("ERROR: " + error)
        return 1

    print("OK: config is valid")
    print("Mode: " + run_mode(config))
    if run_mode(config) == "ltx_cloud":
        try:
            load_ltx_api_key(config)
            print("LTX API key: configured")
        except Exception as exc:
            print("LTX API key: " + str(exc))
            return 1
    else:
        print("LTX repo: " + config["ltx_repo_path"])
        print("LTX HDR script: " + str(resolve_script_path(config)))
    print("LTX python: " + config["ltx_python"])
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

    if run_mode(config) == "ltx_cloud":
        try:
            return convert_cloud(args, config, input_path, (job_dir, output_dir, log_path, manifest_path))
        except Exception as exc:
            message = "LTX cloud conversion failed: " + str(exc)
            print(message, file=sys.stderr)
            write_failure_manifest(args, config, 3, message, command=["ltx_cloud"], job_paths=(job_dir, output_dir, log_path, manifest_path))
            return 3

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
