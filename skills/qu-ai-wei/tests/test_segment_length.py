"""Deterministic arithmetic and CLI boundary checks, not model quality tests."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "segment_length.py"
SPEC = importlib.util.spec_from_file_location("segment_length", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SegmentLengthTests(unittest.TestCase):
    def test_threshold_is_average_not_every_fragment(self):
        result = MODULE.measure("12345，123456789012345。")
        self.assertEqual((result["status"], result["average"], result["segment_lengths"]),
                         ("pass", 10.0, [5, 15]))

    def test_below_threshold_fails(self):
        result = MODULE.measure("123456789，1234567890")
        self.assertEqual((result["status"], result["average"]), ("fail", 9.5))

    def test_punctuation_whitespace_and_mixed_characters(self):
        result = MODULE.measure("中A1 +￥，乙、丙：丁——戊。")
        self.assertEqual(result["segment_lengths"], [5, 4])

    def test_all_five_boundaries_and_empty_fragments(self):
        result = MODULE.measure("一。二？三！四，五；六，，。")
        self.assertEqual(result["segment_lengths"], [1, 1, 1, 1, 1, 1])

    def test_paragraphs_do_not_join_but_soft_wraps_do(self):
        result = MODULE.measure("12345\n67890\n \n12345\r\n\r\n67890")
        self.assertEqual(result["segment_lengths"], [10, 5, 5])

    def test_average_is_weighted_by_segments(self):
        result = MODULE.measure("12345，12345\n\n12345678901234567890")
        self.assertEqual((result["characters"], result["segments"], result["average"]), (30, 3, 10.0))

    def test_no_applicable_prose_is_not_a_pass(self):
        result = MODULE.measure("\ufeff\n ，。？！；—— ")
        self.assertEqual((result["status"], result["segments"], result["average"]),
                         ("not_applicable", 0, None))

    def test_cli_exit_codes_and_file_read_only(self):
        with tempfile.TemporaryDirectory(prefix="qu-ai-wei-count-") as directory:
            path = Path(directory) / "prose.txt"
            for text, expected in [("一二三四五六七八九十。", 0), ("短句。", 1), ("", 2)]:
                original = ("\ufeff" + text).encode("utf-8")
                path.write_bytes(original)
                result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPT), str(path)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(path.read_bytes(), original)
            missing = subprocess.run([sys.executable, "-B", str(SCRIPT), str(path.with_name("missing.txt"))],
                                     capture_output=True)
            self.assertEqual(missing.returncode, 2)
        stdin = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPT), "-"],
                               input="一二三四五六七八九十。".encode("utf-8"), capture_output=True)
        self.assertEqual(stdin.returncode, 0, stdin.stderr)


if __name__ == "__main__":
    unittest.main()
