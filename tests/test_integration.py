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
ALL_PDF = list((GEN / "attacked").glob("*.pdf")) + list((GEN / "clean").glob("*.pdf"))
ATTACKED_PDF = list((GEN / "attacked").glob("*.pdf"))
CLEAN_PDF = list((GEN / "clean").glob("*.pdf"))
ALL_DOCX = list((GEN / "attacked").glob("*.docx")) + list((GEN / "clean").glob("*.docx"))
ATTACKED_DOCX = list((GEN / "attacked").glob("*.docx"))
CLEAN_DOCX = list((GEN / "clean").glob("*.docx"))
ALL_HTML = list((GEN / "attacked").glob("*.html")) + list((GEN / "clean").glob("*.html"))
ATTACKED_HTML = list((GEN / "attacked").glob("*.html"))
CLEAN_HTML = list((GEN / "clean").glob("*.html"))


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
            write_html_report(result, out)
            sp = write_safe_outputs(result, out)
            report = json.loads(jp.read_text(encoding="utf-8"))
            self.assertTrue(report["issues"])
            # re-scan safe text -> must be clean
            safe = sp["safe_text"].read_text(encoding="utf-8")
            rescan = TXTScanner().scan_text(safe)
            self.assertEqual(rescan.issues, [])


class PDFIntegrationTests(unittest.TestCase):
    def test_all_pdf_files_scannable(self):
        self.assertGreater(len(ALL_PDF), 0)
        for f in ALL_PDF:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertTrue(result.sha256)
                self.assertEqual(result.file_type, "application/pdf")

    def test_all_attacked_pdf_detected(self):
        self.assertGreater(len(ATTACKED_PDF), 0)
        for f in ATTACKED_PDF:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertTrue(result.issues, f"missed attack: {f.name}")

    def test_all_clean_pdf_no_false_positive(self):
        self.assertGreater(len(CLEAN_PDF), 0)
        for f in CLEAN_PDF:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertFalse(result.issues, f"false positive: {f.name}")

    def test_white_text_pdf_visible_excludes_payload(self):
        f = GEN / "attacked" / "attacked_0001_resume_pdf_white_text.pdf"
        result = run_scan(f)
        self.assertIn("ST-PDF-HIDDEN-TEXT-WHITE", result.issue_codes)
        self.assertIn("TEST PAYLOAD", result.extracted_text)
        self.assertNotIn("TEST PAYLOAD", result.visible_text)

    def test_offpage_pdf_detected(self):
        f = GEN / "attacked" / "attacked_0009_claim_pdf_offpage_text.pdf"
        result = run_scan(f)
        self.assertIn("ST-PDF-OFFPAGE-TEXT", result.issue_codes)

    def test_pdf_end_to_end_leakage_zero(self):
        f = GEN / "attacked" / "attacked_0001_resume_pdf_white_text.pdf"
        result = run_scan(f)
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            sp = write_safe_outputs(result, out)
            safe = sp["safe_text"].read_text(encoding="utf-8")
            rescan = TXTScanner().scan_text(safe)
            self.assertEqual(rescan.issues, [])


class DOCXIntegrationTests(unittest.TestCase):
    def test_all_docx_files_scannable(self):
        self.assertGreater(len(ALL_DOCX), 0)
        for f in ALL_DOCX:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertTrue(result.sha256)
                self.assertEqual(
                    result.file_type,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )

    def test_all_attacked_docx_detected(self):
        self.assertGreater(len(ATTACKED_DOCX), 0)
        for f in ATTACKED_DOCX:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertTrue(result.issues, f"missed attack: {f.name}")

    def test_all_clean_docx_no_false_positive(self):
        self.assertGreater(len(CLEAN_DOCX), 0)
        for f in CLEAN_DOCX:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertFalse(result.issues, f"false positive: {f.name}")

    def test_tiny_text_docx_detected(self):
        f = GEN / "attacked" / "attacked_0002_rfp_docx_tiny_text.docx"
        result = run_scan(f)
        self.assertIn("ST-DOCX-TINY-TEXT", result.issue_codes)

    def test_metadata_prompt_docx_detected(self):
        f = GEN / "attacked" / "attacked_0010_vendor_docx_metadata_prompt.docx"
        result = run_scan(f)
        self.assertIn("ST-DOCX-METADATA-PROMPT", result.issue_codes)

    def test_docx_end_to_end_leakage_zero(self):
        f = GEN / "attacked" / "attacked_0002_rfp_docx_tiny_text.docx"
        result = run_scan(f)
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            sp = write_safe_outputs(result, out)
            safe = sp["safe_text"].read_text(encoding="utf-8")
            rescan = TXTScanner().scan_text(safe)
            self.assertEqual(rescan.issues, [])


class HTMLIntegrationTests(unittest.TestCase):
    def test_all_html_files_scannable(self):
        self.assertGreater(len(ALL_HTML), 0)
        for f in ALL_HTML:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertTrue(result.sha256)
                self.assertEqual(result.file_type, "text/html")

    def test_all_attacked_html_detected(self):
        self.assertGreater(len(ATTACKED_HTML), 0)
        for f in ATTACKED_HTML:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertTrue(result.issues, f"missed attack: {f.name}")

    def test_all_clean_html_no_false_positive(self):
        self.assertGreater(len(CLEAN_HTML), 0)
        for f in CLEAN_HTML:
            with self.subTest(file=f.name):
                result = run_scan(f)
                self.assertFalse(result.issues, f"false positive: {f.name}")

    def test_metadata_prompt_html_detected(self):
        f = GEN / "attacked" / "attacked_0003_grant_html_metadata_prompt.html"
        result = run_scan(f)
        self.assertIn("ST-HTML-METADATA-PROMPT", result.issue_codes)

    def test_html_end_to_end_leakage_zero(self):
        f = GEN / "attacked" / "attacked_0003_grant_html_metadata_prompt.html"
        result = run_scan(f)
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            sp = write_safe_outputs(result, out)
            safe = sp["safe_text"].read_text(encoding="utf-8")
            rescan = TXTScanner().scan_text(safe)
            self.assertEqual(rescan.issues, [])


if __name__ == "__main__":
    unittest.main()
