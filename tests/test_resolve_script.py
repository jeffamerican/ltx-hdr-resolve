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
            self.assertEqual(
                [
                    "Scene_12_A_ltx_hdr_part_002_of_003_frame_000182.exr",
                    "Scene_12_A_ltx_hdr_part_002_of_003_frame_000183.exr",
                    "Scene_12_A_ltx_hdr_part_002_of_003_frame_000184.exr",
                ],
                sorted(path.name for path in exr_dir.glob("*.exr")),
            )
            sequence_path, start_index, end_index = ltx_hdr_resolve._find_exr_sequence(str(exr_dir))
            self.assertTrue(sequence_path.endswith("Scene_12_A_ltx_hdr_part_002_of_003_frame_%06d.exr"))
            self.assertEqual(182, start_index)
            self.assertEqual(184, end_index)

    def test_segment_label_identifies_shared_clip_part_and_frame_range(self):
        label = ltx_hdr_resolve._segment_label("Hero Shot", 3, 4, 365, 41)

        self.assertEqual("Hero Shot LTX HDR part 003 of 004 frames 000365-000405", label)


if __name__ == "__main__":
    unittest.main()
