import tempfile
import unittest
import json
import io
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ltx_hdr_worker


class WorkerTests(unittest.TestCase):
    def make_config(self, root):
        repo = root / "LTX-Video"
        repo.mkdir()
        ltx_python = repo / ".venv" / "bin" / "python"
        ltx_python.parent.mkdir(parents=True)
        ltx_python.write_text("")
        script = repo / "run_hdr_ic_lora.py"
        script.write_text("")

        models = root / "models"
        models.mkdir()
        config = {
            "ltx_repo_path": str(repo),
            "ltx_python": str(ltx_python),
            "ltx_hdr_script": "run_hdr_ic_lora.py",
            "output_root": str(root / "output"),
            "distilled_checkpoint": str(models / "ltx-2.3-22b-distilled-1.1.safetensors"),
            "upscaler": str(models / "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"),
            "lora": str(models / "ltx-2.3-22b-ic-lora-hdr-0.9.safetensors"),
            "text_embeddings": str(models / "ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors"),
            "exr_half": True,
            "high_quality": False,
            "skip_mp4": True,
            "max_frames": 49,
            "spatial_tile": 768,
            "offload": "cpu",
        }
        for key in ("distilled_checkpoint", "upscaler", "lora", "text_embeddings"):
            Path(config[key]).write_text("")
        return config

    def test_validate_config_accepts_complete_local_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.make_config(Path(temp_dir))
            self.assertEqual([], ltx_hdr_worker.validate_config(config))

    def test_load_config_accepts_windows_utf8_bom(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"ltx_repo_path": "C:\\LTX-Video"}), encoding="utf-8-sig")

            config = ltx_hdr_worker.load_config(path)

        self.assertEqual("C:\\LTX-Video", config["ltx_repo_path"])

    def test_build_ltx_command_matches_hdr_script_flags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.make_config(Path(temp_dir))
            command = ltx_hdr_worker.build_ltx_command(config, "/tmp/input.mp4", "/tmp/out")

        self.assertIn("--distilled-checkpoint", command)
        self.assertIn("--upscaler", command)
        self.assertIn("--lora", command)
        self.assertIn("--text-embeddings", command)
        self.assertIn("--exr-half", command)
        self.assertNotIn("--high-quality", command)
        self.assertIn("--skip-mp4", command)
        self.assertEqual(command[-2:], ["--max-frames", "49"])

    def test_build_ltx_command_matches_ltx2_pipeline_flags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.make_config(Path(temp_dir))
            hdr_script = Path(config["ltx_repo_path"]) / "packages" / "ltx-pipelines" / "src" / "ltx_pipelines" / "hdr_ic_lora.py"
            hdr_script.parent.mkdir(parents=True)
            hdr_script.write_text("")
            config["ltx_hdr_script"] = "packages/ltx-pipelines/src/ltx_pipelines/hdr_ic_lora.py"
            command = ltx_hdr_worker.build_ltx_command(config, "/tmp/input.mp4", "/tmp/out")

        self.assertEqual(command[:3], [config["ltx_python"], "-m", "ltx_pipelines.hdr_ic_lora"])
        self.assertIn("--distilled-checkpoint-path", command)
        self.assertIn("--spatial-upsampler-path", command)
        self.assertIn("--hdr-lora", command)
        self.assertIn("--text-embeddings", command)
        self.assertIn("--num-frames", command)
        self.assertIn("--spatial-tile", command)
        self.assertIn("--offload", command)

    def test_find_outputs_discovers_exr_folder_and_frame_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            exr_dir = output_dir / "shot_exr"
            exr_dir.mkdir()
            for frame in range(3):
                (exr_dir / ("frame_%05d.exr" % frame)).write_text("")
            (output_dir / "shot.mp4").write_text("")

            result = ltx_hdr_worker.find_outputs("/tmp/shot.mp4", output_dir)

        self.assertEqual(str(exr_dir), result["exr_dir"])
        self.assertEqual(3, result["exr_frame_count"])
        self.assertTrue(result["preview_mp4"].endswith("shot.mp4"))

    def test_convert_validation_failure_emits_manifest_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config))
            args = SimpleNamespace(config=str(config_path), input=str(root / "missing.mp4"), clip_name="Missing Shot")
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                returncode = ltx_hdr_worker.convert(args)

            self.assertEqual(2, returncode)
            marker_line = [line for line in stdout.getvalue().splitlines() if line.startswith(ltx_hdr_worker.MANIFEST_MARKER)][0]
            manifest_path = Path(marker_line[len(ltx_hdr_worker.MANIFEST_MARKER) :])
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual("failed", manifest["status"])
            self.assertIn("input does not exist", manifest["error"])

    def test_ltx_package_paths_discovers_local_package_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            expected = []
            for package in ("ltx-core", "ltx-pipelines"):
                source_path = Path(config["ltx_repo_path"]) / "packages" / package / "src"
                source_path.mkdir(parents=True)
                expected.append(str(source_path))

            paths = ltx_hdr_worker.ltx_package_paths(config)

        self.assertEqual(expected, paths)

    def test_format_elapsed(self):
        self.assertEqual("0m 00s", ltx_hdr_worker.format_elapsed(0))
        self.assertEqual("1m 05s", ltx_hdr_worker.format_elapsed(65))
        self.assertEqual("1h 01m 05s", ltx_hdr_worker.format_elapsed(3665))

    def test_describe_windows_access_violation(self):
        detail = ltx_hdr_worker.describe_returncode(3221225477)

        self.assertIn("0xC0000005", detail)
        self.assertIn("access violation", detail)


if __name__ == "__main__":
    unittest.main()
