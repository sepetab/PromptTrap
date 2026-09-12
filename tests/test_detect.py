"""Tests for content-based file type detection."""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from purifydocs.scanner.detect import DOCX, HTML, PDF, TXT, UNKNOWN, detect_format, detect_mime


class DetectFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def _write(self, name: str, data: bytes) -> pathlib.Path:
        path = self.tmp / name
        path.write_bytes(data)
        return path

    def test_pdf_by_content(self):
        path = self._write("doc.pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<</Type/Catalog>>endobj")
        self.assertEqual(detect_format(path), PDF)
        self.assertEqual(detect_mime(path), "application/pdf")

    def test_pdf_with_wrong_extension(self):
        # A PDF renamed to .txt must still be detected as PDF by content.
        path = self._write("notes.txt", b"%PDF-1.4\n%binary\n1 0 obj<</Type/Catalog>>endobj")
        self.assertEqual(detect_format(path), PDF)

    def test_txt_by_content(self):
        path = self._write("claim.txt", "Insurance Claim Summary: 4cbd87a\nClaimant: Daniel\n".encode())
        self.assertEqual(detect_format(path), TXT)
        self.assertEqual(detect_mime(path), "text/plain")

    def test_txt_with_pdf_extension_is_still_txt(self):
        path = self._write("trick.pdf", "Just a plain text resume, not a PDF.\n".encode())
        self.assertEqual(detect_format(path), TXT)

    def test_html_by_doctype(self):
        html = b'<!doctype html>\n<html lang="en"><head><title>Grant</title></head><body>x</body></html>'
        path = self._write("grant.html", html)
        self.assertEqual(detect_format(path), HTML)

    def test_html_with_txt_extension(self):
        html = b"<html><head><title>x</title></head><body><p>hi</p></body></html>"
        path = self._write("page.txt", html)
        self.assertEqual(detect_format(path), HTML)

    def test_html_fragment_with_tags(self):
        # No doctype, but multiple HTML tags -> HTML.
        html = b"<div><p>hello</p><span>world</span></div>"
        path = self._write("frag.html", html)
        self.assertEqual(detect_format(path), HTML)

    def test_plain_text_not_mistaken_for_html(self):
        # Contains a stray '<' but is mostly text and has no HTML tags.
        path = self._write("math.txt", "if a < b and b < c then a < c\nplain prose here\n".encode())
        self.assertEqual(detect_format(path), TXT)

    def test_docx_by_content(self):
        import zipfile

        path = self.tmp / "rfp.docx"
        with zipfile.ZipFile(str(path), "w") as z:
            z.writestr("word/document.xml", '<?xml version="1.0"?><w:document/>')
            z.writestr("[Content_Types].xml", "<Types/>")
        self.assertEqual(detect_format(path), DOCX)
        self.assertEqual(
            detect_mime(path),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_docx_with_zip_extension(self):
        import zipfile

        path = self._write("archive.zip", b"")
        with zipfile.ZipFile(str(path), "w") as z:
            z.writestr("word/document.xml", "<w:document/>")
        self.assertEqual(detect_format(path), DOCX)

    def test_zip_without_docx_parts_is_unknown(self):
        import zipfile

        path = self._write("data.zip", b"")
        with zipfile.ZipFile(str(path), "w") as z:
            z.writestr("unrelated.txt", "hello")
        self.assertEqual(detect_format(path), UNKNOWN)

    def test_empty_file_falls_back_to_extension(self):
        path = self._write("empty.txt", b"")
        self.assertEqual(detect_format(path), TXT)
        path2 = self._write("empty.pdf", b"")
        self.assertEqual(detect_format(path2), PDF)

    def test_unrecognised_binary_is_unknown(self):
        path = self._write("blob.bin", bytes(range(256)))
        self.assertEqual(detect_format(path), UNKNOWN)


class DispatchByContentTests(unittest.TestCase):
    """The scanner router must use content, so a misnamed file routes correctly."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_misnamed_pdf_routes_to_pdf_scanner(self):
        from purifydocs.scanner import get_scanner
        from purifydocs.scanner.pdf import PDFScanner

        path = self.tmp / "resume.txt"
        path.write_bytes(b"%PDF-1.4\n%binary\n1 0 obj<</Type/Catalog>>endobj")
        self.assertIsInstance(get_scanner(path), PDFScanner)

    def test_misnamed_txt_routes_to_txt_scanner(self):
        from purifydocs.scanner import get_scanner
        from purifydocs.scanner.txt import TXTScanner

        path = self.tmp / "trick.pdf"
        path.write_text("plain text, not a pdf\n", encoding="utf-8")
        self.assertIsInstance(get_scanner(path), TXTScanner)


if __name__ == "__main__":
    unittest.main()
