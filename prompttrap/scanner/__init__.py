"""Document scanners for extracting text and locating injection payloads."""
from __future__ import annotations

from pathlib import Path

from prompttrap.scanner.base import BaseScanner, ScanResult
from prompttrap.scanner.pdf import PDFScanner
from prompttrap.scanner.txt import TXTScanner

_SCANNERS: dict[str, type[BaseScanner]] = {
    ".txt": TXTScanner,
    ".pdf": PDFScanner,
}


def get_scanner(path: Path) -> BaseScanner:
    suffix = path.suffix.lower()
    cls = _SCANNERS.get(suffix)
    if cls is None:
        raise ValueError(f"No scanner registered for extension: {suffix}")
    return cls()


def scan(path: Path | str) -> ScanResult:
    path = Path(path)
    return get_scanner(path).scan(path)
