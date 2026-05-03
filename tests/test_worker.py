import tempfile
import unittest
from pathlib import Path

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
            "distilled_checkpoint": str(models / "ltx-2.3-22b-distilled.safetensors"),
            "upscaler": str(models / "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"),
            "lora": str(models / "ltx-2.3-22b-ic-lora-hdr-0.9.safetensors"),
            "text_embeddings": str(models / "ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors"),
            "exr_half": True,
            "high_quality": True,
            "max_frames": 161,
        }
        for key in ("distilled_checkpoint", "upscaler", "lora", "text_embeddings"):
            Path(config[key]).write_text("")
        return config

    def test_validate_config_accepts_complete_local_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.make_config(Path(temp_dir))
            self.assertEqual([], ltx_hdr_worker.validate_config(config))

    def test_build_ltx_command_matches_hdr_script_flags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.make_config(Path(temp_dir))
            command = ltx_hdr_worker.build_ltx_command(config, "/tmp/input.mp4", "/tmp/out")

        self.assertIn("--distilled-checkpoint", command)
        self.assertIn("--upscaler", command)
        self.assertIn("--lora", command)
        self.assertIn("--text-embeddings", command)
        self.assertIn("--exr-half", command)
        self.assertIn("--high-quality", command)
        self.assertEqual(command[-2:], ["--max-frames", "161"])

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


if __name__ == "__main__":
    unittest.main()
