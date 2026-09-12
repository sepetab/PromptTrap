"""Content-based file type detection.

Detects format by reading file content (magic bytes / zip structure) rather
than relying on the file extension. This satisfies the scanner-methodology
requirement to "detect type by content, not only extension".

A purpose-built sniffer is used for the four supported formats (PDF, DOCX,
HTML, TXT) instead of a generic libmagic wrapper so that detection has no
system-level dependency and behaves identically on Windows, macOS, and Linux.
The file extension is only consulted as a last-resort fallback when content
sniffing is inconclusive.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

# Canonical format names used for scanner dispatch.
PDF = "pdf"
DOCX = "docx"
HTML = "html"
TXT = "txt"
UNKNOWN = "unknown"

_MIME_BY_FORMAT: dict[str, str] = {
    PDF: "application/pdf",
    DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    HTML: "text/html",
    TXT: "text/plain",
    UNKNOWN: "application/octet-stream",
}

_EXT_FALLBACK: dict[str, str] = {
    ".pdf": PDF,
    ".docx": DOCX,
    ".html": HTML,
    ".htm": HTML,
    ".txt": TXT,
}

_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

_HTML_OPENERS = (b"<!doctype html", b"<!doctype html", b"<html", b"<?xml")
_HTML_TAGS = (b"<head", b"<body", b"<div", b"<span", b"<p>", b"<title", b"<a ", b"<ul")


def detect_format(path: Path | str, *, head_size: int = 8192) -> str:
    """Return the canonical format name for ``path`` by content, with ext fallback."""
    path = Path(path)
    try:
        with path.open("rb") as f:
            head = f.read(head_size)
    except OSError:
        head = b""

    fmt = _sniff(head, path)
    if fmt is not UNKNOWN:
        return fmt

    # Last resort: extension. Better than nothing for empty/edge-case files.
    return _EXT_FALLBACK.get(path.suffix.lower(), UNKNOWN)


def detect_mime(path: Path | str) -> str:
    """Return a MIME type string derived from content detection."""
    return _MIME_BY_FORMAT[detect_format(path)]


def _sniff(head: bytes, path: Path) -> str:
    if head.startswith(b"%PDF"):
        return PDF
    if head[:4] in _ZIP_MAGICS:
        return _sniff_docx(path)
    if _looks_like_html(head):
        return HTML
    if _is_text(head):
        return TXT
    return UNKNOWN


def _sniff_docx(path: Path) -> str:
    """A DOCX is a ZIP archive containing ``word/document.xml``."""
    try:
        with zipfile.ZipFile(str(path)) as z:
            if "word/document.xml" in z.namelist():
                return DOCX
    except (zipfile.BadZipFile, OSError):
        pass
    return UNKNOWN


def _looks_like_html(head: bytes) -> bool:
    sample = head[:1024]
    if not sample:
        return False
    # Strip a leading UTF-8 BOM and leading whitespace.
    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:]
    stripped = sample.lstrip()
    low = stripped[:512].lower()

    if any(low.startswith(opener) for opener in (b"<!doctype html", b"<html", b"<?xml")):
        return True
    if b"<html" in low:
        return True
    # Multiple distinct HTML tags within the opening window imply an HTML doc.
    hits = sum(1 for tag in _HTML_TAGS if tag in low)
    return hits >= 2


def _is_text(head: bytes) -> bool:
    """Heuristic: treat decodable, non-null content as plain text."""
    sample = head[:1024]
    if not sample:
        return False
    if b"\x00" in sample:
        return False
    try:
        decoded = sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            decoded = sample.decode("latin-1")
        except UnicodeDecodeError:
            return False
    # Must be mostly printable / whitespace.
    if not decoded.strip():
        return False
    printable = sum(1 for ch in decoded if ch.isprintable() or ch in "\t\n\r\f\v")
    return printable / max(1, len(decoded)) >= 0.80
