"""Document scanners for extracting text and locating injection payloads."""
from __future__ import annotations

from pathlib import Path

from purifydocs.scanner.base import BaseScanner, ScanResult
from purifydocs.scanner.detect import DOCX, HTML, PDF, TXT, detect_format
from purifydocs.scanner.docx import DOCXScanner
from purifydocs.scanner.html import HTMLScanner
from purifydocs.scanner.pdf import PDFScanner
from purifydocs.scanner.txt import TXTScanner

# Dispatch maps a detected *format* (content-based) to a scanner class.
_SCANNERS: dict[str, type[BaseScanner]] = {
    TXT: TXTScanner,
    PDF: PDFScanner,
    DOCX: DOCXScanner,
    HTML: HTMLScanner,
}


def get_scanner(path: Path | str) -> BaseScanner:
    fmt = detect_format(path)
    cls = _SCANNERS.get(fmt)
    if cls is None:
        raise ValueError(f"No scanner registered for detected format: {fmt!r} (path: {path})")
    return cls()


def scan(path: Path | str) -> ScanResult:
    path = Path(path)
    return get_scanner(path).scan(path)
