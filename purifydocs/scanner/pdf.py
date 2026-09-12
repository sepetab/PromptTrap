"""PDF scanner: extracts text and detects hidden/coordinate-based manipulation.

Detectors:
  * white / near-white text invisible against the page background
  * tiny text (font size below a threshold)
  * off-page text (drawn outside the page mediabox)
  * prompt-like / base64 / zero-width payloads in PDF annotations
  * prompt-like / base64 / zero-width payloads embedded in document metadata
  * general zero-width / base64 / prompt-like payloads in extracted text
  * best-effort OCR-vs-extracted mismatch (skipped if tesseract unavailable)
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar
from pypdf import PdfReader

from purifydocs.scanner.base import BaseScanner, Issue, ScanResult
from purifydocs.scanner.txt import TXTScanner

# A font size at or below this is treated as invisible-to-humans "tiny" text.
TINY_FONT_SIZE = 3.0

# RGB components above this are considered near-white (background-coloured).
NEAR_WHITE_THRESHOLD = 0.9

# Tolerance (points) outside the page mediabox before flagging off-page text.
OFFPAGE_MARGIN = 5.0

# Maximum number of pages to OCR for mismatch detection (perf guard).
OCR_MAX_PAGES = 3

# Minimum rapidfuzz similarity between extracted and OCR text before flagging.
OCR_MISMATCH_THRESHOLD = 0.70


class PDFScanner(BaseScanner):
    name = "pdf"

    def scan(self, path: Path) -> ScanResult:
        path = Path(path)
        start = time.perf_counter()
        sha = self.sha256_of(path)
        raw_bytes = path.read_bytes()
        issues: list[Issue] = []
        extracted_parts: list[str] = []
        visible_parts: list[str] = []
        metadata: dict[str, Any] = {}

        reader = PdfReader(str(path))
        metadata = self._read_metadata(reader)
        issues.extend(self._scan_metadata(metadata))

        for page_index, page in enumerate(reader.pages):
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            lines = self._extract_lines(path, page_index)
            for line in lines:
                extracted_parts.append(line.text)
                if line.is_visible(width, height):
                    visible_parts.append(line.text)
                issues.extend(line.issues(width, height, page_index))

            # Scan page annotations (sticky notes, free text, highlights, etc.)
            issues.extend(self._scan_annotations(page, page_index))

        extracted_text = "\n".join(extracted_parts)
        visible_text = "\n".join(visible_parts)

        # Re-use the general TXT detectors on the full machine-readable text so
        # zero-width / base64 / prompt-like payloads hidden inside PDF text
        # are caught with the same codes as plain text files.
        general = TXTScanner().scan_text(extracted_text)
        for issue in general.issues:
            if issue not in issues:
                issues.append(issue)

        # Best-effort OCR mismatch check. Rendered visible text should match
        # what a human sees; a large gap between OCR and extracted text implies
        # machine-readable content that is not visually present.
        ocr_issue = self._ocr_mismatch(path, extracted_text)
        if ocr_issue is not None:
            issues.append(ocr_issue)

        elapsed_ms = (time.perf_counter() - start) * 1000
        return ScanResult(
            path=str(path),
            file_type=self.detect_type(path),
            sha256=sha,
            size_bytes=len(raw_bytes),
            issues=issues,
            extracted_text=extracted_text,
            visible_text=visible_text,
            metadata=metadata,
            processing_time_ms=round(elapsed_ms, 3),
        )

    @staticmethod
    def _read_metadata(reader: PdfReader) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if reader.metadata:
            for key, value in reader.metadata.items():
                meta[str(key)] = str(value)
        return meta

    def _scan_metadata(self, metadata: dict[str, Any]) -> list[Issue]:
        issues: list[Issue] = []
        if not metadata:
            return issues
        for key, value in metadata.items():
            text = value if isinstance(value, str) else str(value)
            general = TXTScanner().scan_text(text)
            if general.issues:
                for issue in general.issues:
                    issues.append(
                        Issue(
                            code="ST-PDF-METADATA-PROMPT",
                            severity=issue.severity,
                            message=f"Manipulation detected in PDF metadata field {key}: {issue.message}",
                            evidence=issue.evidence,
                            location={"field": key},
                        )
                    )
        return issues

    def _scan_annotations(self, page: Any, page_index: int) -> list[Issue]:
        """Scan PDF annotations for prompt-like / encoded payloads.

        PDF annotations (sticky notes, free text, highlights, etc.) can carry
        hidden text in their ``/Contents``, ``/RC`` (rich content), and ``/T``
        (title/author) fields. Each field is run through the TXT detectors.
        """
        issues: list[Issue] = []
        annots = page.get("/Annots")
        if not annots:
            return issues

        for ai, annot_ref in enumerate(annots):
            try:
                annot = annot_ref.get_object()
            except Exception:
                continue

            subtype = str(annot.get("/Subtype", "")).lstrip("/")
            fields = {
                "Contents": annot.get("/Contents"),
                "RC": annot.get("/RC"),
                "T": annot.get("/T"),
            }

            for field_name, value in fields.items():
                if value is None:
                    continue
                text = str(value)
                if not text.strip():
                    continue
                general = TXTScanner().scan_text(text)
                if general.issues:
                    issues.append(
                        Issue(
                            code="ST-PDF-ANNOTATION-PROMPT",
                            severity="high",
                            message=(
                                f"Prompt-like / encoded payload in PDF annotation "
                                f"({subtype}) field /{field_name}."
                            ),
                            evidence=text[:200],
                            location={
                                "page": page_index,
                                "annotation_index": ai,
                                "subtype": subtype,
                                "field": field_name,
                            },
                        )
                    )
        return issues

    @staticmethod
    def _extract_lines(path: Path, page_index: int) -> list[_PdfLine]:
        lines: list[_PdfLine] = []
        for layout in extract_pages(str(path), page_numbers=[page_index]):
            current: list[_PdfChar] = []

            def walk(obj: Any) -> None:
                if isinstance(obj, LTChar):
                    current.append(_PdfChar.from_ltchar(obj))
                    return
                for child in getattr(obj, "__iter__", lambda: [])():
                    walk(child)

            walk(layout)

            # Group chars into reading-order lines by shared baseline (y).
            current.sort(key=lambda c: (round(c.y, 1), c.x))
            grouped: dict[float, list[_PdfChar]] = {}
            for ch in current:
                grouped.setdefault(round(ch.y, 1), []).append(ch)
            for y in sorted(grouped, reverse=True):
                chars = sorted(grouped[y], key=lambda c: c.x)
                lines.append(_PdfLine(page_index, y, chars))
            break
        return lines

    def _ocr_mismatch(self, path: Path, extracted_text: str) -> Issue | None:
        if not extracted_text.strip():
            return None
        try:
            import pypdfium2 as pdfium
            import pytesseract
            from PIL import Image
        except Exception:
            return None

        try:
            doc = pdfium.PdfDocument(str(path))
            images: list[str] = []
            page_count = min(len(doc), OCR_MAX_PAGES)
            for i in range(page_count):
                page = doc[i]
                bitmap = page.render(scale=1.5)
                pil = bitmap.to_pil() if hasattr(bitmap, "to_pil") else Image.fromarray(
                    bitmap.to_array()
                )
                images.append(pytesseract.image_to_string(pil))
                page.close()
            doc.close()
            ocr_text = "\n".join(images)
        except Exception:
            return None

        try:
            from rapidfuzz import fuzz

            ratio = fuzz.ratio(self._normalize(extracted_text), self._normalize(ocr_text)) / 100.0
        except Exception:
            return None

        if ratio < OCR_MISMATCH_THRESHOLD:
            return Issue(
                code="ST-PDF-OCR-MISMATCH",
                severity="medium",
                message=(
                    f"OCR text differs substantially from parser-extracted text "
                    f"(similarity {ratio:.2f}); hidden machine-readable content suspected."
                ),
                evidence=ocr_text[:200],
                location={"similarity": round(ratio, 3)},
            )
        return None

    @staticmethod
    def _normalize(text: str) -> str:
        import re

        return re.sub(r"\s+", " ", text or "").strip().lower()


class _PdfChar:
    __slots__ = ("x", "y", "size", "color", "text")

    def __init__(self, x: float, y: float, size: float, color: tuple | None, text: str):
        self.x = x
        self.y = y
        self.size = size
        self.color = color
        self.text = text

    @classmethod
    def from_ltchar(cls, ch: LTChar) -> _PdfChar:
        try:
            nc = ch.graphicstate.ncolor
            color = tuple(round(float(c), 3) for c in nc) if hasattr(nc, "__iter__") else None
        except Exception:
            color = None
        return cls(round(ch.x0, 3), round(ch.y0, 3), round(ch.size, 3), color, ch.get_text())


class _PdfLine:
    __slots__ = ("page", "y", "chars")

    def __init__(self, page: int, y: float, chars: list[_PdfChar]):
        self.page = page
        self.y = y
        self.chars = chars

    @property
    def text(self) -> str:
        return "".join(c.text for c in self.chars)

    def _line_color(self) -> tuple | None:
        colors = [c.color for c in self.chars if c.color is not None]
        if not colors:
            return None
        # Return the most common color in this line.
        return max(set(colors), key=colors.count)

    def _is_near_white(self) -> bool:
        color = self._line_color()
        if color is None:
            return False
        if len(color) < 3:
            return False
        return all(c >= NEAR_WHITE_THRESHOLD for c in color[:3])

    def _min_size(self) -> float:
        return min((c.size for c in self.chars), default=0.0)

    def _min_x(self) -> float:
        return min((c.x for c in self.chars), default=0.0)

    def _min_y(self) -> float:
        return self.y

    def is_visible(self, width: float, height: float) -> bool:
        return (
            not self._is_near_white()
            and self._min_size() > TINY_FONT_SIZE
            and self._min_x() >= -OFFPAGE_MARGIN
            and self._min_y() >= -OFFPAGE_MARGIN
            and self._min_x() <= width + OFFPAGE_MARGIN
            and self._min_y() <= height + OFFPAGE_MARGIN
        )

    def issues(self, width: float, height: float, page_index: int) -> list[Issue]:
        out: list[Issue] = []
        text = self.text.strip()
        if not text:
            return out
        loc = {"page": page_index, "y": self.y}

        if self._is_near_white():
            out.append(
                Issue(
                    code="ST-PDF-HIDDEN-TEXT-WHITE",
                    severity="high",
                    message="White / near-white text drawn on a light background is invisible to humans.",
                    evidence=text[:200],
                    location={**loc, "color": self._line_color()},
                )
            )

        if self._min_size() <= TINY_FONT_SIZE:
            out.append(
                Issue(
                    code="ST-PDF-TINY-TEXT",
                    severity="high",
                    message=f"Tiny text (font size {self._min_size():.2f}pt) is effectively invisible.",
                    evidence=text[:200],
                    location={**loc, "font_size": self._min_size()},
                )
            )

        min_x = self._min_x()
        min_y = self._min_y()
        if (
            min_x < -OFFPAGE_MARGIN
            or min_y < -OFFPAGE_MARGIN
            or min_x > width + OFFPAGE_MARGIN
            or min_y > height + OFFPAGE_MARGIN
        ):
            out.append(
                Issue(
                    code="ST-PDF-OFFPAGE-TEXT",
                    severity="high",
                    message="Text drawn outside the page media box is not visible to a reader.",
                    evidence=text[:200],
                    location={**loc, "x": min_x, "page_width": width, "page_height": height},
                )
            )

        return out
