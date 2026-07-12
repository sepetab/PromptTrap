"""Document scanners for extracting text and locating injection payloads."""
from __future__ import annotations

from pathlib import Path

from prompttrap.scanner.base import BaseScanner, ScanResult
from prompttrap.scanner.detect import DOCX, PDF, TXT, detect_format
from prompttrap.scanner.docx import DOCXScanner
from prompttrap.scanner.pdf import PDFScanner
from prompttrap.scanner.txt import TXTScanner

# Dispatch maps a detected *format* (content-based) to a scanner class.
_SCANNERS: dict[str, type[BaseScanner]] = {
    TXT: TXTScanner,
    PDF: PDFScanner,
    DOCX: DOCXScanner,
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
