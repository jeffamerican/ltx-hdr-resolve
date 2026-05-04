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
import traceback


PLUGIN_ROOT = os.environ.get("LTX_HDR_PLUGIN_ROOT", "")
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.ltx-hdr-resolve/config.json")


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


def _clip_file_path(media_pool_item):
    props = media_pool_item.GetClipProperty() or {}
    for key in ("File Path", "FilePath", "Path", "Source File", "SourceFile"):
        value = props.get(key)
        if value:
            return value
    return ""


def _worker_path():
    root = PLUGIN_ROOT
    if not root:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    return os.path.join(root, "src", "ltx_hdr_worker.py")


def _load_manifest(manifest_path):
    with open(manifest_path, "r") as handle:
        return json.load(handle)


def _manifest_path_from_output(output):
    marker = "LTX_HDR_MANIFEST="
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(marker):
            return line[len(marker) :].strip()
    return ""


def _format_worker_failure(manifest, manifest_path, fallback):
    detail = manifest.get("error") or fallback or "Unknown worker failure."
    message = "LTX HDR conversion failed.\n" + detail
    log_path = manifest.get("log_path")
    if log_path:
        message += "\n\nLog: " + log_path
    if manifest_path:
        message += "\nManifest: " + manifest_path
    return message


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


def _import_exr_sequence(project, exr_dir, name):
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
    try:
        item.SetMetadata({"Comments": "Generated by LTX HDR Resolve v1 from " + name})
    except Exception:
        pass
    return item


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

    current_item = timeline.GetCurrentVideoItem()
    if not current_item:
        _alert("Move the playhead onto a video clip before running LTX HDR.")
        return

    media_pool_item = current_item.GetMediaPoolItem()
    if not media_pool_item:
        _alert("Current timeline item has no source media-pool item.")
        return

    clip_path = _clip_file_path(media_pool_item)
    if not clip_path or not os.path.exists(clip_path):
        _alert("Could not resolve the current clip's source file path.")
        return

    worker = _worker_path()
    if not os.path.exists(worker):
        _alert("Worker not found at " + worker)
        return

    config_path = os.environ.get("LTX_HDR_CONFIG", DEFAULT_CONFIG_PATH)
    if not os.path.exists(config_path):
        _alert("Missing config: " + config_path)
        return

    command = [
        sys.executable,
        worker,
        "convert",
        "--config",
        config_path,
        "--input",
        clip_path,
        "--clip-name",
        current_item.GetName() or media_pool_item.GetName() or "clip",
    ]

    _alert("Starting local LTX HDR conversion for: " + os.path.basename(clip_path))
    completed = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = completed.communicate()
    output = stdout.decode("utf-8", "replace") if hasattr(stdout, "decode") else str(stdout)
    err_output = stderr.decode("utf-8", "replace") if hasattr(stderr, "decode") else str(stderr)
    manifest_path = _manifest_path_from_output(output)
    manifest = None
    if manifest_path and os.path.exists(manifest_path):
        manifest = _load_manifest(manifest_path)

    if completed.returncode != 0:
        if manifest:
            _alert(_format_worker_failure(manifest, manifest_path, err_output or output))
            return
        detail = err_output or output
        if manifest_path:
            detail = "Worker reported a manifest path, but the file was not found:\n" + manifest_path + "\n\n" + detail
        _alert("LTX HDR conversion failed before it wrote a readable manifest.\n" + detail[-1200:])
        return

    if not manifest:
        _alert("LTX HDR conversion did not return a manifest path.\n" + (output + "\n" + err_output)[-1200:])
        return

    if manifest.get("status") != "completed":
        _alert(_format_worker_failure(manifest, manifest_path, err_output or output))
        return

    exr_dir = manifest.get("exr_dir")
    if not exr_dir or not os.path.isdir(exr_dir):
        _alert("Conversion completed but no EXR directory was reported.")
        return

    imported_item = _import_exr_sequence(project, exr_dir, current_item.GetName() or "clip")
    try:
        current_item.AddTake(imported_item)
        current_item.FinalizeTake()
        _alert("Imported LTX HDR EXR sequence and added it as a take.")
    except Exception:
        _alert("Imported LTX HDR EXR sequence into the LTX HDR bin. AddTake was not accepted by Resolve for this clip.")


if __name__ == "__main__":
    try:
        if "--debug-env" in sys.argv:
            debug_environment()
        else:
            main()
    except Exception:
        _alert("Unexpected LTX HDR error:\n" + traceback.format_exc())
