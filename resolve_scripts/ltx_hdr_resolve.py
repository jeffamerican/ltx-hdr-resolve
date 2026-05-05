#!/usr/bin/env python3
"""Resolve-side entrypoint for LTX HDR conversion.

This module intentionally uses only the Python standard library. Resolve's
embedded interpreter should only coordinate the job and import the result.
"""

from __future__ import print_function

import glob
import importlib
import json
import os
import subprocess
import sys
import time
import traceback


PLUGIN_ROOT = os.environ.get("LTX_HDR_PLUGIN_ROOT", "")
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.ltx-hdr-resolve/config.json")
LOG_MARKER = "LTX_HDR_LOG="
MANIFEST_MARKER = "LTX_HDR_MANIFEST="
STATUS_MARKER = "LTX_HDR_STATUS="
VIDEO_EXTENSIONS = (".mp4", ".mov", ".mxf")
DEFAULT_LTX_1080P_MAX_FRAMES = 181
DEFAULT_LTX_1440P_MAX_FRAMES = 101
DEFAULT_LTX_4K_MAX_FRAMES = 41


def _resolve_app():
    candidates = [globals()]
    main_module = sys.modules.get("__main__")
    if main_module:
        candidates.append(getattr(main_module, "__dict__", {}))

    for namespace in candidates:
        app = namespace.get("resolve")
        if app:
            return app

        fusion_app = namespace.get("fusion")
        if fusion_app:
            try:
                app = fusion_app.GetResolve()
                if app:
                    return app
            except Exception:
                pass

        bmd_app = namespace.get("bmd")
        if bmd_app:
            try:
                app = bmd_app.scriptapp("Resolve")
                if app:
                    return app
            except Exception:
                pass

    for module_name in ("DaVinciResolveScript", "BlackmagicFusion"):
        try:
            module = importlib.import_module(module_name)
            app = module.scriptapp("Resolve")
            if app:
                return app
        except Exception:
            pass

    script_paths = []
    if os.name == "nt":
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        script_paths.append(os.path.join(program_data, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting", "Modules"))
        script_paths.append(os.path.join(program_data, "Blackmagic Design", "DaVinci Resolve", "Developer", "Scripting", "Modules"))
    else:
        script_paths.extend(
            [
                "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
                "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
            ]
        )

    for script_path in script_paths:
        if script_path and os.path.exists(script_path) and script_path not in sys.path:
            sys.path.append(script_path)

    try:
        import DaVinciResolveScript as dvr_script

        return dvr_script.scriptapp("Resolve")
    except Exception:
        return None


def debug_environment():
    lines = []
    lines.append("Python executable: " + sys.executable)
    lines.append("Python version: " + sys.version.replace("\n", " "))
    lines.append("PLUGIN_ROOT: " + (PLUGIN_ROOT or "<unset>"))
    config_path = os.environ.get("LTX_HDR_CONFIG", DEFAULT_CONFIG_PATH)
    lines.append("Config path: " + config_path)
    if os.path.exists(config_path):
        try:
            config = _load_config(config_path)
            lines.append("Configured LTX Python: " + str(config.get("ltx_python", "<missing>")))
        except Exception as exc:
            lines.append("Config load error: " + repr(exc))
    lines.append("sys.path:")
    for path in sys.path:
        lines.append("  " + path)
    for name in ("resolve", "fusion", "bmd"):
        lines.append(name + " global: " + ("yes" if globals().get(name) else "no"))
    try:
        import DaVinciResolveScript as dvr_script

        lines.append("DaVinciResolveScript import: yes")
        app = dvr_script.scriptapp("Resolve")
        lines.append("scriptapp('Resolve'): " + ("yes" if app else "no"))
    except Exception as exc:
        lines.append("DaVinciResolveScript import/scriptapp error: " + repr(exc))
    app = _resolve_app()
    lines.append("_resolve_app(): " + ("yes" if app else "no"))
    _alert("\n".join(lines))


def _alert(message):
    print("[LTX HDR] " + message)
    try:
        app = _resolve_app()
        if app:
            fusion = app.Fusion()
            if fusion:
                fusion.UIManager.MessageBox({"Text": "LTX HDR", "InformativeText": message})
    except Exception:
        pass


def _log(message):
    print("[LTX HDR] " + message)


def _open_resolve_page(app, page_name):
    try:
        app.OpenPage(page_name)
    except Exception:
        pass


def _clip_file_path(media_pool_item):
    props = media_pool_item.GetClipProperty() or {}
    for key in ("File Path", "FilePath", "Path", "Source File", "SourceFile"):
        value = props.get(key)
        if value:
            return value
    return ""


def _safe_name(value):
    safe = []
    for char in value or "clip":
        if char.isalnum() or char in ("-", "_", "."):
            safe.append(char)
        else:
            safe.append("_")
    cleaned = "".join(safe).strip("._")
    return cleaned or "clip"


def _display_name(value):
    cleaned = " ".join(str(value or "clip").split())
    return cleaned or "clip"


def _segment_label(base_name, segment_index, segment_count, first_frame, frame_count):
    base = _display_name(base_name)
    if segment_count <= 1:
        return base + " LTX HDR frames " + str(first_frame).zfill(6) + "-" + str(first_frame + max(frame_count, 1) - 1).zfill(6)
    return (
        base
        + " LTX HDR part "
        + str(segment_index).zfill(3)
        + " of "
        + str(segment_count).zfill(3)
        + " frames "
        + str(first_frame).zfill(6)
        + "-"
        + str(first_frame + max(frame_count, 1) - 1).zfill(6)
    )


def _render_custom_name(base_name, segment_index, segment_count, start, mark_out):
    safe = _safe_name(base_name)
    if len(safe) > 40:
        safe = safe[:40].strip("._") or "clip"
    return (
        safe
        + "_ltxhdr_p"
        + str(segment_index).zfill(3)
        + "of"
        + str(segment_count).zfill(3)
        + "_f"
        + str(start)
        + "_"
        + str(mark_out)
    )


def _worker_path():
    root = PLUGIN_ROOT
    if not root:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    return os.path.join(root, "src", "ltx_hdr_worker.py")


def _load_config(config_path):
    with open(config_path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _load_manifest(manifest_path):
    with open(manifest_path, "r") as handle:
        return json.load(handle)


def _manifest_path_from_output(output):
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(MANIFEST_MARKER):
            return line[len(MANIFEST_MARKER) :].strip()
    return ""


def _parse_worker_line(line):
    line = line.strip()
    if line.startswith(MANIFEST_MARKER):
        return "manifest", line[len(MANIFEST_MARKER) :].strip()
    if line.startswith(LOG_MARKER):
        return "log", line[len(LOG_MARKER) :].strip()
    if line.startswith(STATUS_MARKER):
        return "status", line[len(STATUS_MARKER) :].strip()
    return "output", line


def _format_worker_failure(manifest, manifest_path, fallback):
    detail = manifest.get("error") or fallback or "Unknown worker failure."
    message = "LTX HDR conversion failed.\n" + detail
    log_path = manifest.get("log_path")
    if log_path:
        message += "\n\nLog: " + log_path
    if manifest_path:
        message += "\nManifest: " + manifest_path
    return message


def _timeline_item_range(timeline_item):
    start = int(timeline_item.GetStart())
    duration = int(timeline_item.GetDuration())
    if duration < 1:
        raise RuntimeError("Timeline item duration is not valid.")
    return start, start + duration - 1, duration


def _set_render_format_for_upload(project):
    candidates = (
        ("mp4", "H264"),
        ("mp4", "H.264"),
        ("mov", "H264"),
        ("mov", "ProRes422"),
    )
    for render_format, codec in candidates:
        try:
            if project.SetCurrentRenderFormatAndCodec(render_format, codec):
                return render_format
        except Exception:
            pass
    return ""


def _start_rendering(project, job_id):
    attempts = (
        lambda: project.StartRendering([job_id], False),
        lambda: project.StartRendering([job_id]),
        lambda: project.StartRendering(job_id, False),
        lambda: project.StartRendering(job_id),
    )
    for attempt in attempts:
        try:
            if attempt():
                return True
        except Exception:
            pass
    return False


def _set_render_settings_with_fallbacks(project, settings):
    attempts = [
        (
            "full",
            settings,
        ),
        (
            "without optional delivery flags",
            {
                "SelectAllFrames": settings["SelectAllFrames"],
                "MarkIn": settings["MarkIn"],
                "MarkOut": settings["MarkOut"],
                "TargetDir": settings["TargetDir"],
                "CustomName": settings["CustomName"],
                "ExportVideo": settings["ExportVideo"],
                "ExportAudio": settings["ExportAudio"],
            },
        ),
        (
            "minimal timeline range",
            {
                "SelectAllFrames": settings["SelectAllFrames"],
                "MarkIn": settings["MarkIn"],
                "MarkOut": settings["MarkOut"],
                "TargetDir": settings["TargetDir"],
                "CustomName": settings["CustomName"],
            },
        ),
    ]
    for label, attempt_settings in attempts:
        try:
            result = project.SetRenderSettings(attempt_settings)
        except Exception as exc:
            _log("Resolve rejected " + label + " render settings: " + repr(exc))
            continue
        if result is not False:
            if label != "full":
                _log("Resolve accepted " + label + " render settings.")
            return True
        _log("Resolve returned false for " + label + " render settings.")
    return False


def _render_status_text(status):
    if not status:
        return ""
    for key in ("JobStatus", "jobStatus", "Status", "status"):
        value = status.get(key)
        if value:
            return str(value)
    return ""


def _render_completion(status):
    if not status:
        return ""
    for key in ("CompletionPercentage", "completionPercentage", "Progress", "progress"):
        value = status.get(key)
        if value is not None:
            return str(value)
    return ""


def _find_rendered_segment(target_dir, custom_name):
    candidates = []
    if not os.path.isdir(target_dir):
        return ""
    for name in os.listdir(target_dir):
        lower = name.lower()
        if name.startswith(custom_name) and lower.endswith(VIDEO_EXTENSIONS):
            path = os.path.join(target_dir, name)
            try:
                candidates.append((os.path.getmtime(path), path))
            except Exception:
                candidates.append((0, path))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


def _timeline_resolution(timeline):
    width = 0
    height = 0
    for key in ("timelineResolutionWidth", "timelineResolutionHeight"):
        try:
            value = int(timeline.GetSetting(key) or 0)
        except Exception:
            value = 0
        if key.endswith("Width"):
            width = value
        else:
            height = value
    return width, height


def _cloud_segment_frame_limit(config, timeline):
    configured = config.get("cloud_segment_frames")
    if configured is not None:
        try:
            configured_int = int(configured)
            if configured_int > 0:
                return configured_int
        except Exception:
            pass

    width, height = _timeline_resolution(timeline)
    largest = max(width, height)
    if largest >= 3840 or height >= 2160:
        return DEFAULT_LTX_4K_MAX_FRAMES
    if largest >= 2560 or height >= 1440:
        return DEFAULT_LTX_1440P_MAX_FRAMES
    return DEFAULT_LTX_1080P_MAX_FRAMES


def _timeline_item_segments(timeline_item, max_frames):
    start, mark_out, duration = _timeline_item_range(timeline_item)
    if max_frames < 1:
        max_frames = duration
    segments = []
    segment_start = start
    index = 1
    while segment_start <= mark_out:
        segment_out = min(mark_out, segment_start + max_frames - 1)
        segments.append(
            {
                "index": index,
                "start": segment_start,
                "mark_out": segment_out,
                "duration": segment_out - segment_start + 1,
            }
        )
        index += 1
        segment_start = segment_out + 1
    return segments


def _render_timeline_item_segment(project, timeline_item, config, segment=None, segment_count=1):
    if segment:
        start = int(segment["start"])
        mark_out = int(segment["mark_out"])
        duration = int(segment["duration"])
        segment_index = int(segment["index"])
    else:
        start, mark_out, duration = _timeline_item_range(timeline_item)
        segment_index = 1
    output_root = config.get("output_root") or os.path.join(os.path.expanduser("~"), ".ltx-hdr-resolve", "output")
    target_dir = os.path.join(output_root, "resolve_exports")
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception:
        pass

    try:
        project.SetCurrentRenderMode(1)
    except Exception:
        pass

    render_format = _set_render_format_for_upload(project)
    if not render_format:
        raise RuntimeError("Could not set a Resolve render format for timeline clip export.")

    custom_name = _render_custom_name(timeline_item.GetName() or "timeline_clip", segment_index, segment_count, start, mark_out)
    settings = {
        "SelectAllFrames": False,
        "MarkIn": start,
        "MarkOut": mark_out,
        "TargetDir": target_dir,
        "CustomName": custom_name,
        "UniqueFilenameStyle": 1,
        "ExportVideo": True,
        "ExportAudio": False,
        "VideoQuality": "Best",
        "NetworkOptimization": True,
    }
    if not _set_render_settings_with_fallbacks(project, settings):
        raise RuntimeError(
            "Resolve rejected render settings for timeline clip export.\n"
            + "Format: "
            + render_format
            + "\nRange: "
            + str(start)
            + "-"
            + str(mark_out)
            + "\nTarget: "
            + target_dir
            + "\nName: "
            + custom_name
        )

    job_id = project.AddRenderJob()
    if not job_id:
        raise RuntimeError("Resolve did not create a render job for timeline clip export.")

    label = ""
    if segment_count > 1:
        label = " segment " + str(segment_index) + "/" + str(segment_count)
    _log("Exporting timeline clip" + label + " range " + str(start) + "-" + str(mark_out) + " (" + str(duration) + " frames) before LTX upload.")
    if not _start_rendering(project, job_id):
        try:
            project.DeleteRenderJob(job_id)
        except Exception:
            pass
        raise RuntimeError("Resolve did not start the timeline clip render job.")

    last_status = ""
    while True:
        status = {}
        try:
            status = project.GetRenderJobStatus(job_id) or {}
        except Exception:
            status = {}
        status_text = _render_status_text(status)
        completion = _render_completion(status)
        if completion and completion != last_status:
            _log("Timeline export progress: " + completion + "%")
            last_status = completion
        if status_text.lower() in ("complete", "completed", "success", "succeeded"):
            break
        if status_text.lower() in ("failed", "cancelled", "canceled"):
            raise RuntimeError("Timeline clip export failed: " + json.dumps(status))
        try:
            if not project.IsRenderingInProgress():
                break
        except Exception:
            pass
        time.sleep(1)

    rendered_path = _find_rendered_segment(target_dir, custom_name)
    try:
        project.DeleteRenderJob(job_id)
    except Exception:
        pass
    if not rendered_path or not os.path.exists(rendered_path):
        raise RuntimeError("Timeline clip export finished but no rendered file was found in " + target_dir)
    return rendered_path, duration


def _selected_media_pool_clip_path(project):
    media_pool = project.GetMediaPool() if project else None
    if not media_pool:
        return "", ""
    try:
        selected = media_pool.GetSelectedClips() or []
    except Exception:
        selected = []
    if len(selected) != 1:
        return "", ""
    clip_path = _clip_file_path(selected[0])
    return clip_path, selected[0].GetName() or os.path.basename(clip_path)


def _timeline_item_for_ltx(timeline):
    try:
        selected = timeline.GetSelectedClips() or []
    except Exception:
        selected = []
    if len(selected) == 1:
        return selected[0], "selected timeline clip"
    if len(selected) > 1:
        raise RuntimeError("Select exactly one timeline clip for LTX HDR.")

    current_item = timeline.GetCurrentVideoItem()
    if current_item:
        return current_item, "timeline clip under playhead"
    return None, ""


def _worker_startup_kwargs():
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


def _find_exr_sequence(exr_dir):
    frames = sorted(glob.glob(os.path.join(exr_dir, "*.exr")))
    if not frames:
        return None, 0, 0
    first = frames[0]
    basename = os.path.basename(first)
    digits = []
    for index in range(len(basename) - 1, -1, -1):
        char = basename[index]
        if char.isdigit():
            digits.append(index)
        elif digits:
            break
    if not digits:
        return first, 0, len(frames) - 1
    start = min(digits)
    end = max(digits) + 1
    first_index = int(basename[start:end])
    return (
        os.path.join(os.path.dirname(first), basename[:start] + "%" + str(end - start).zfill(2) + "d" + basename[end:]),
        first_index,
        first_index + len(frames) - 1,
    )


def _normalize_exr_sequence_names(exr_dir, base_name, segment_index, segment_count, first_frame):
    frames = sorted(glob.glob(os.path.join(exr_dir, "*.exr")))
    if not frames:
        raise RuntimeError("No EXR frames found in " + exr_dir)

    prefix = _safe_name(base_name) + "_ltx_hdr"
    if segment_count > 1:
        prefix += "_part_" + str(segment_index).zfill(3) + "_of_" + str(segment_count).zfill(3)

    staged = []
    for index, frame_path in enumerate(frames):
        temp_path = os.path.join(exr_dir, ".__ltx_hdr_rename_" + str(segment_index).zfill(3) + "_" + str(index).zfill(6) + ".exr")
        while os.path.exists(temp_path):
            temp_path = temp_path[:-4] + "_tmp.exr"
        os.rename(frame_path, temp_path)
        staged.append(temp_path)

    final_paths = []
    for index, temp_path in enumerate(staged):
        frame_number = first_frame + index
        final_path = os.path.join(exr_dir, prefix + "_frame_" + str(frame_number).zfill(6) + ".exr")
        os.rename(temp_path, final_path)
        final_paths.append(final_path)

    return len(final_paths)


def _set_imported_item_label(item, label):
    attempts = (
        lambda: item.SetClipProperty("Clip Name", label),
        lambda: item.SetClipProperty("Name", label),
        lambda: item.SetName(label),
    )
    for attempt in attempts:
        try:
            if attempt():
                return True
        except Exception:
            pass
    return False


def _import_exr_sequence(project, exr_dir, name, metadata=None):
    media_pool = project.GetMediaPool()
    if not media_pool:
        raise RuntimeError("No media pool is available.")

    root = media_pool.GetRootFolder()
    target_folder = media_pool.GetCurrentFolder()
    try:
        target_folder = media_pool.AddSubFolder(root, "LTX HDR") or target_folder
        media_pool.SetCurrentFolder(target_folder)
    except Exception:
        pass

    frames = sorted(glob.glob(os.path.join(exr_dir, "*.exr")))
    if not frames:
        raise RuntimeError("No EXR frames found in " + exr_dir)

    sequence_path, start_index, end_index = _find_exr_sequence(exr_dir)
    imported = None

    if sequence_path and "%" in sequence_path:
        imported = media_pool.ImportMedia(
            [
                {
                    "FilePath": sequence_path,
                    "StartIndex": start_index,
                    "EndIndex": end_index,
                }
            ]
        )
    if not imported:
        imported = media_pool.ImportMedia([exr_dir])
    if not imported:
        imported = media_pool.ImportMedia(frames)
    if not imported:
        raise RuntimeError("Resolve did not import the generated EXR sequence.")

    item = imported[0]
    _set_imported_item_label(item, name)
    try:
        comments = "Generated by LTX HDR Resolve v1 from " + name
        if metadata:
            comments += "\n" + metadata
        item.SetMetadata({"Comments": comments})
    except Exception:
        pass
    return item


def _run_worker_conversion(worker_python, worker, config_path, clip_path, clip_name):
    command = [
        worker_python,
        worker,
        "convert",
        "--config",
        config_path,
        "--input",
        clip_path,
        "--clip-name",
        clip_name or "clip",
    ]

    _log("Starting LTX HDR conversion for: " + os.path.basename(clip_path))
    _log("Using LTX Python: " + worker_python)
    completed = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
        **_worker_startup_kwargs()
    )

    output_lines = []
    manifest_path = ""
    log_path = ""
    if completed.stdout:
        for line in completed.stdout:
            output_lines.append(line)
            kind, value = _parse_worker_line(line)
            if kind == "manifest":
                manifest_path = value
            elif kind == "log":
                log_path = value
                _log("Worker log: " + value)
            elif kind == "status" and value:
                _log(value)
            elif value:
                _log(value)

    completed.wait()
    output = "".join(output_lines)
    err_output = ""
    if not manifest_path:
        manifest_path = _manifest_path_from_output(output)
    manifest = None
    if manifest_path and os.path.exists(manifest_path):
        manifest = _load_manifest(manifest_path)

    if completed.returncode != 0:
        if manifest:
            raise RuntimeError(_format_worker_failure(manifest, manifest_path, err_output or output))
        detail = err_output or output
        if manifest_path:
            detail = "Worker reported a manifest path, but the file was not found:\n" + manifest_path + "\n\n" + detail
        if log_path:
            detail += "\n\nLog: " + log_path
        raise RuntimeError("LTX HDR conversion failed before it wrote a readable manifest.\n" + detail[-1200:])

    if not manifest:
        detail = output + "\n" + err_output
        if log_path:
            detail += "\n\nLog: " + log_path
        raise RuntimeError("LTX HDR conversion did not return a manifest path.\n" + detail[-1200:])

    if manifest.get("status") != "completed":
        raise RuntimeError(_format_worker_failure(manifest, manifest_path, err_output or output))

    return manifest


def main():
    app = _resolve_app()
    if not app:
        _alert("Resolve scripting API is not available.")
        return

    project_manager = app.GetProjectManager()
    project = project_manager.GetCurrentProject() if project_manager else None
    timeline = project.GetCurrentTimeline() if project else None
    if not project or not timeline:
        _alert("Open a project and timeline before running LTX HDR.")
        return

    try:
        current_item, timeline_item_source = _timeline_item_for_ltx(timeline)
    except Exception as exc:
        _alert(str(exc))
        return

    worker = _worker_path()
    if not os.path.exists(worker):
        _alert("Worker not found at " + worker)
        return

    config_path = os.environ.get("LTX_HDR_CONFIG", DEFAULT_CONFIG_PATH)
    if not os.path.exists(config_path):
        _alert("Missing config: " + config_path)
        return

    try:
        config = _load_config(config_path)
    except Exception as exc:
        _alert("Could not read config: " + config_path + "\n" + str(exc))
        return

    worker_python = config.get("ltx_python") or ""
    if not worker_python:
        _alert("Config is missing ltx_python: " + config_path)
        return
    if not os.path.exists(worker_python):
        _alert("Configured LTX Python was not found:\n" + worker_python + "\n\nRun Install-Windows.cmd again.")
        return

    conversion_inputs = []
    base_clip_name = ""
    if current_item:
        try:
            base_clip_name = current_item.GetName() or "timeline_clip"
            segment_limit = _cloud_segment_frame_limit(config, timeline)
            segments = _timeline_item_segments(current_item, segment_limit)
            total_frames = sum(segment["duration"] for segment in segments)
            if len(segments) > 1:
                _log("Timeline clip is " + str(total_frames) + " frames; auto-segmenting into " + str(len(segments)) + " chunks of up to " + str(segment_limit) + " frames.")
            next_output_frame = 1
            for segment in segments:
                clip_path, timeline_frame_count = _render_timeline_item_segment(project, current_item, config, segment, len(segments))
                clip_name = _segment_label(base_clip_name, segment["index"], len(segments), next_output_frame, timeline_frame_count)
                conversion_inputs.append(
                    {
                        "path": clip_path,
                        "name": clip_name,
                        "base_name": base_clip_name,
                        "frames": timeline_frame_count,
                        "index": segment["index"],
                        "segment_count": len(segments),
                        "output_frame_start": next_output_frame,
                        "timeline_start": segment["start"],
                        "timeline_mark_out": segment["mark_out"],
                    }
                )
                next_output_frame += timeline_frame_count
        except Exception as exc:
            _open_resolve_page(app, "edit")
            _alert("Could not export the timeline clip range for LTX HDR:\n" + str(exc))
            return
        _open_resolve_page(app, "edit")
        _log("Exported " + timeline_item_source + " into " + str(len(conversion_inputs)) + " segment(s).")
    else:
        clip_path, clip_name = _selected_media_pool_clip_path(project)
        if not clip_path:
            _alert("Move the playhead onto a timeline video clip, or select exactly one source clip in the Media Pool.")
            return
        _log("No timeline clip under the playhead; using selected Media Pool source clip.")
        conversion_inputs.append(
            {
                "path": clip_path,
                "name": _display_name(clip_name or "clip") + " LTX HDR",
                "base_name": clip_name or "clip",
                "frames": 0,
                "index": 1,
                "segment_count": 1,
                "output_frame_start": 1,
                "timeline_start": 0,
                "timeline_mark_out": 0,
            }
        )

    imported_items = []
    for item in conversion_inputs:
        clip_path = item["path"]
        clip_name = item["name"]
        if not clip_path or not os.path.exists(clip_path):
            _alert("Could not resolve an input clip path for LTX HDR.")
            return
        try:
            manifest = _run_worker_conversion(worker_python, worker, config_path, clip_path, clip_name)
        except Exception as exc:
            _alert(str(exc))
            return

        exr_dir = manifest.get("exr_dir")
        if not exr_dir or not os.path.isdir(exr_dir):
            _alert("Conversion completed but no EXR directory was reported.")
            return
        actual_frame_count = _normalize_exr_sequence_names(
            exr_dir,
            item.get("base_name") or clip_name,
            int(item.get("index") or 1),
            int(item.get("segment_count") or 1),
            int(item.get("output_frame_start") or 1),
        )
        segment_count = int(item.get("segment_count") or 1)
        segment_index = int(item.get("index") or 1)
        imported_label = _segment_label(
            item.get("base_name") or clip_name,
            segment_index,
            segment_count,
            int(item.get("output_frame_start") or 1),
            actual_frame_count,
        )
        metadata = (
            "Segment "
            + str(segment_index)
            + " of "
            + str(segment_count)
            + "; output frames "
            + str(int(item.get("output_frame_start") or 1)).zfill(6)
            + "-"
            + str(int(item.get("output_frame_start") or 1) + actual_frame_count - 1).zfill(6)
        )
        if item.get("timeline_start") or item.get("timeline_mark_out"):
            metadata += "; timeline frames " + str(item.get("timeline_start")) + "-" + str(item.get("timeline_mark_out"))
        imported_items.append(_import_exr_sequence(project, exr_dir, imported_label, metadata))

    if current_item and len(imported_items) == 1:
        try:
            current_item.AddTake(imported_items[0])
            current_item.FinalizeTake()
            _alert("Imported LTX HDR EXR sequence and added it as a take.")
            return
        except Exception:
            _alert("Imported LTX HDR EXR sequence into the LTX HDR bin. AddTake was not accepted by Resolve for this clip.")
            return

    if len(imported_items) > 1:
        _alert("Imported " + str(len(imported_items)) + " labeled LTX HDR EXR segment sequences into the LTX HDR bin with continuous frame numbering.")
    else:
        _alert("Imported LTX HDR EXR sequence into the LTX HDR bin.")


if __name__ == "__main__":
    try:
        if "--debug-env" in sys.argv:
            debug_environment()
        else:
            main()
    except Exception:
        _alert("Unexpected LTX HDR error:\n" + traceback.format_exc())
