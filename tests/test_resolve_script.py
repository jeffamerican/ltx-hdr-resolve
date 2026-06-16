import importlib.util
import tempfile
import unittest
from pathlib import Path


RESOLVE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "resolve_scripts" / "ltx_hdr_resolve.py"
SPEC = importlib.util.spec_from_file_location("ltx_hdr_resolve", RESOLVE_SCRIPT_PATH)
ltx_hdr_resolve = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ltx_hdr_resolve)


class ResolveScriptTests(unittest.TestCase):
    def test_normalize_exr_sequence_names_keeps_segment_frame_numbers_continuous(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exr_dir = Path(temp_dir)
            for frame in range(3):
                (exr_dir / ("raw_%04d.exr" % frame)).write_text("")

            count = ltx_hdr_resolve._normalize_exr_sequence_names(str(exr_dir), "Scene 12/A", 2, 3, 182)

            self.assertEqual(3, count)
            names = sorted(path.name for path in exr_dir.glob("*.exr"))
            self.assertEqual(3, len(names))
            self.assertTrue(names[0].startswith("Scene_12_A_"))
            self.assertTrue(names[0].endswith("_ltx_hdr_part_002_of_003_frame_000182.exr"))
            self.assertTrue(names[1].endswith("_ltx_hdr_part_002_of_003_frame_000183.exr"))
            self.assertTrue(names[2].endswith("_ltx_hdr_part_002_of_003_frame_000184.exr"))
            sequence_path, start_index, end_index = ltx_hdr_resolve._find_exr_sequence(str(exr_dir))
            self.assertTrue(sequence_path.endswith("_ltx_hdr_part_002_of_003_frame_%06d.exr"))
            self.assertEqual(182, start_index)
            self.assertEqual(184, end_index)

    def test_segment_label_identifies_shared_clip_part_and_frame_range(self):
        label = ltx_hdr_resolve._segment_label("Hero Shot", 3, 4, 365, 41)

        self.assertEqual("Hero Shot LTX HDR part 003 of 004 frames 000365-000405", label)

    def test_render_custom_name_is_short_and_segmented(self):
        name = ltx_hdr_resolve._render_custom_name("Very Long Scene Name " * 6, 12, 14, 1000, 1040)

        self.assertLessEqual(len(name), 80)
        self.assertIn("_ltxhdr_p012of014_f1000_1040", name)

    def test_oversize_rendered_segment_splits_with_safety_margin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rendered = Path(temp_dir) / "segment.mp4"
            rendered.write_bytes(b"x" * 102)
            segment = {"index": 1, "start": 100, "mark_out": 140, "duration": 41}

            split = ltx_hdr_resolve._split_segment_for_upload(segment, str(rendered), 100)

        self.assertEqual(2, len(split))
        self.assertLess(split[0]["duration"], segment["duration"])
        self.assertEqual(100, split[0]["start"])
        self.assertEqual(140, split[-1]["mark_out"])
        self.assertEqual(41, sum(item["duration"] for item in split))

    def test_cloud_upload_limit_bytes_uses_default_for_invalid_config(self):
        self.assertEqual(32 * 1024 * 1024, ltx_hdr_resolve._cloud_upload_limit_bytes({"cloud_upload_limit_mb": "bad"}))
        self.assertEqual(32 * 1024 * 1024, ltx_hdr_resolve._cloud_upload_limit_bytes({"cloud_upload_limit_mb": 0}))
        self.assertEqual(32 * 1024 * 1024, ltx_hdr_resolve._cloud_upload_limit_bytes({"cloud_upload_limit_mb": -1}))

    def test_cloud_upload_limit_bytes_caps_legacy_high_config(self):
        self.assertEqual(32 * 1024 * 1024, ltx_hdr_resolve._cloud_upload_limit_bytes({"cloud_upload_limit_mb": 100}))
        self.assertEqual(16 * 1024 * 1024, ltx_hdr_resolve._cloud_upload_limit_bytes({"cloud_upload_limit_mb": 16}))

    def test_tag_ltx_hdr_color_space_uses_aces_linear_srgb_candidates(self):
        class FakeItem:
            def __init__(self):
                self.calls = []

            def SetClipProperty(self, key, value):
                self.calls.append((key, value))
                return key == "ACES Input Transform"

        item = FakeItem()

        accepted = ltx_hdr_resolve._tag_ltx_hdr_color_space(item)

        self.assertEqual(["ACES Input Transform"], accepted)
        self.assertIn(("ACES Input Transform", "sRGB (Linear) - CSC"), item.calls)
        self.assertIn(("Input Gamma", "Linear"), item.calls)


if __name__ == "__main__":
    unittest.main()
