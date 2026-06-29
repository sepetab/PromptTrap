"""Integration test: end-to-end scan -> sanitize -> report."""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from prompttrap.scanner import scan as run_scan
from prompttrap.sanitizer.safe_payload import write_safe_outputs
from prompttrap.reports.json_report import write_json_report
from prompttrap.reports.html_report import write_html_report
from prompttrap.scanner.txt import TXTScanner

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEN = ROOT / "samples" / "PromptTrap_Data_Generator" / "prompttrap_data_starter" / "data_sample" / "generated"

ALL_TXT = list((GEN / "attacked").glob("*.txt")) + list((GEN / "clean").glob("*.txt"))


class IntegrationTests(unittest.TestCase):
    def test_all_txt_files_scannable(self):
        for f in ALL_TXT:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertTrue(result.sha256)
                self.assertEqual(result.file_type, "text/plain")

    def test_all_attacked_txt_detected(self):
        attacked = list((GEN / "attacked").glob("*.txt"))
        self.assertGreater(len(attacked), 0)
        for f in attacked:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertTrue(result.issues, f"missed attack: {f.name}")

    def test_all_clean_txt_no_false_positive(self):
        clean = list((GEN / "clean").glob("*.txt"))
        self.assertGreater(len(clean), 0)
        for f in clean:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertFalse(result.issues, f"false positive: {f.name}")

    def test_end_to_end_outputs_and_leakage(self):
        f = GEN / "attacked" / "attacked_0004_claim_zero_width_unicode.txt"
        result = run_scan(f)
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            jp = write_json_report(result, out)
            hp = write_html_report(result, out)
            sp = write_safe_outputs(result, out)
            report = json.loads(jp.read_text(encoding="utf-8"))
            self.assertTrue(report["issues"])
            # re-scan safe text -> must be clean
            safe = sp["safe_text"].read_text(encoding="utf-8")
            rescan = TXTScanner().scan_text(safe)
            self.assertEqual(rescan.issues, [])


if __name__ == "__main__":
    unittest.main()
