"""Unit tests for the TXT scanner, sanitizer, and reports."""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from purifydocs.scanner import scan as run_scan
from purifydocs.scanner.txt import TXTScanner
from purifydocs.sanitizer.safe_text import safe_text
from purifydocs.sanitizer.safe_payload import safe_payload, write_safe_outputs
from purifydocs.reports.json_report import write_json_report
from purifydocs.reports.html_report import write_html_report

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEN = ROOT / "samples" / "PurifyDocs_Data_Generator" / "purifydocs_data_starter" / "data_sample" / "generated"
ATTACKED = GEN / "attacked"
CLEAN = GEN / "clean"

ZERO_WIDTH_FILE = ATTACKED / "attacked_0004_claim_zero_width_unicode.txt"
BASE64_FILE = ATTACKED / "attacked_0008_grant_base64_instruction.txt"
PROMPT_FILE = ATTACKED / "attacked_0012_rfp_plain_prompt_like_text.txt"
CLEAN_FILE = CLEAN / "clean_0004_claim.txt"


class TXTScannerTests(unittest.TestCase):
    def test_clean_file_has_no_issues(self):
        result = TXTScanner().scan(CLEAN_FILE)
        self.assertEqual(result.issues, [], f"unexpected issues: {result.issue_codes}")

    def test_zero_width_detected(self):
        result = TXTScanner().scan(ZERO_WIDTH_FILE)
        self.assertIn("ST-GEN-ZERO-WIDTH", result.issue_codes)
        # visible text should have zero-width chars stripped
        self.assertNotIn("\u200b", result.visible_text)

    def test_base64_detected(self):
        result = TXTScanner().scan(BASE64_FILE)
        self.assertIn("ST-GEN-BASE64-INSTRUCTION", result.issue_codes)

    def test_prompt_like_detected(self):
        result = TXTScanner().scan(PROMPT_FILE)
        self.assertIn("ST-GEN-PROMPT-LIKE-INSTRUCTION", result.issue_codes)

    def test_sha256_matches(self):
        import hashlib
        expected = hashlib.sha256(ZERO_WIDTH_FILE.read_bytes()).hexdigest()
        result = TXTScanner().scan(ZERO_WIDTH_FILE)
        self.assertEqual(result.sha256, expected)


class SanitizerTests(unittest.TestCase):
    def test_safe_text_strips_zero_width(self):
        result = TXTScanner().scan(ZERO_WIDTH_FILE)
        clean = safe_text(result)
        for c in ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"]:
            self.assertNotIn(c, clean)

    def test_safe_text_removes_base64(self):
        result = TXTScanner().scan(BASE64_FILE)
        clean = safe_text(result)
        # the base64 token should be gone
        self.assertNotIn("VEVTVCBQQVlMT0FE", clean)

    def test_safe_text_removes_prompt_line(self):
        result = TXTScanner().scan(PROMPT_FILE)
        clean = safe_text(result)
        self.assertNotIn("TEST PAYLOAD ONLY", clean)

    def test_safe_payload_has_hashes(self):
        result = TXTScanner().scan(ZERO_WIDTH_FILE)
        payload = safe_payload(result)
        self.assertTrue(payload["source_sha256"])
        self.assertTrue(payload["safe_sha256"])
        self.assertNotEqual(payload["source_sha256"], payload["safe_sha256"])

    def test_zero_leakage_after_sanitization(self):
        for f in [ZERO_WIDTH_FILE, BASE64_FILE, PROMPT_FILE]:
            with self.subTest(file=f.name):
                result = TXTScanner().scan(f)
                clean = safe_text(result)
                rescan = TXTScanner().scan_text(clean)
                self.assertEqual(rescan.issues, [], f"leakage in {f.name}: {rescan.issue_codes}")


class ReportTests(unittest.TestCase):
    def test_json_report_writes_file(self):
        result = TXTScanner().scan(ZERO_WIDTH_FILE)
        with tempfile.TemporaryDirectory() as td:
            path = write_json_report(result, pathlib.Path(td))
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("issues", data)
            self.assertTrue(data["issues"])

    def test_html_report_writes_file(self):
        result = TXTScanner().scan(ZERO_WIDTH_FILE)
        with tempfile.TemporaryDirectory() as td:
            path = write_html_report(result, pathlib.Path(td))
            content = path.read_text(encoding="utf-8")
            self.assertIn("ST-GEN-ZERO-WIDTH", content)

    def test_full_scan_output(self):
        result = run_scan(ZERO_WIDTH_FILE)
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            write_json_report(result, out)
            write_html_report(result, out)
            write_safe_outputs(result, out)
            for name in ["report.json", "evidence.html", "safe_text.txt", "safe_payload.json"]:
                self.assertTrue((out / name).is_file(), f"missing {name}")


if __name__ == "__main__":
    unittest.main()
