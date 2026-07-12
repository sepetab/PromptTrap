"""DOCX scanner: extracts text and detects hidden manipulation in .docx files.

A DOCX is a ZIP archive of OOXML parts. This scanner inspects the raw XML
directly (via zipfile + lxml) rather than relying on python-docx, because
python-docx has uneven support for comments, headers/footers, and run-level
formatting across versions, and direct XML access is the most reliable way to
find every place a payload can hide.

Detectors:
  * white / near-white run text (invisible against a light background)
  * tiny run text (font size below a threshold)
  * hidden runs (``<w:vanish/>`` run property)
  * prompt-like / base64 / zero-width payloads in document comments
  * prompt-like / base64 / zero-width payloads in headers and footers
  * prompt-like / base64 / zero-width payloads in drawing alt text (descr/title)
  * prompt-like / base64 / zero-width payloads in core metadata (subject,
    comments, keywords)
  * general zero-width / base64 / prompt-like payloads in extracted text
"""
from __future__ import annotations

import re
import time
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from prompttrap.scanner.base import BaseScanner, Issue, ScanResult
from prompttrap.scanner.txt import TXTScanner

# OOXML namespaces used by Word documents.
_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
}

# A run font size (in half-points) at or below this is "tiny". The synthetic
# generator uses w:sz val="2" (1pt); real documents rarely go below 6pt.
TINY_HALF_POINTS = 4.0

# Hex color values treated as near-white / background-coloured.
NEAR_WHITE_COLORS = {"ffffff", "fefefe", "fffafa", "fffff0", "f8f8ff", "white"}


class DOCXScanner(BaseScanner):
    name = "docx"

    def scan(self, path: Path) -> ScanResult:
        path = Path(path)
        start = time.perf_counter()
        sha = self.sha256_of(path)
        raw_bytes = path.read_bytes()

        issues: list[Issue] = []
        extracted_parts: list[str] = []
        visible_parts: list[str] = []
        metadata: dict[str, Any] = {}

        with zipfile.ZipFile(str(path)) as z:
            names = z.namelist()

            # Core metadata (docProps/core.xml).
            metadata = self._read_core_props(z)

            # Main document body.
            doc_tree = self._read_xml(z, "word/document.xml")
            if doc_tree is not None:
                body_text, body_visible, body_issues = self._scan_body(doc_tree)
                extracted_parts.append(body_text)
                visible_parts.append(body_visible)
                issues.extend(body_issues)
                # Alt text on drawings in the document body.
                issues.extend(self._scan_alt_text(doc_tree, "word/document.xml"))

            # Comments.
            issues.extend(self._scan_comments(z, names))

            # Headers and footers.
            issues.extend(self._scan_headers_footers(z, names))

        extracted_text = "\n".join(p for p in extracted_parts if p)
        visible_text = "\n".join(p for p in visible_parts if p)

        # Re-use the general TXT detectors on the full machine-readable text so
        # zero-width / base64 / prompt-like payloads in document text are
        # caught with the same codes as plain text files.
        general = TXTScanner().scan_text(extracted_text)
        for issue in general.issues:
            if issue not in issues:
                issues.append(issue)

        # Scan metadata fields for payloads.
        issues.extend(self._scan_metadata(metadata))

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

    def _read_core_props(self, z: zipfile.ZipFile) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        tree = self._read_xml(z, "docProps/core.xml")
        if tree is None:
            return meta
        root = tree.getroot()
        for tag in ("subject", "comments", "keywords", "title", "creator"):
            elem = root.find(f"cp:{tag}", _NS)
            if elem is not None and (elem.text or "").strip():
                meta[tag] = elem.text
        return meta

    def _scan_body(self, tree: etree._ElementTree) -> tuple[str, str, list[Issue]]:
        root = tree.getroot()
        issues: list[Issue] = []
        extracted_lines: list[str] = []
        visible_lines: list[str] = []

        for pi, p in enumerate(root.iter(f"{{{_NS['w']}}}p")):
            line_text = ""
            line_visible = ""
            for run in p.iter(f"{{{_NS['w']}}}r"):
                run_text = self._run_text(run)
                if not run_text:
                    continue
                line_text += run_text
                rpr = run.find("w:rPr", _NS)
                if self._is_visible_run(rpr):
                    line_visible += run_text
                else:
                    issues.extend(self._run_issues(rpr, run_text, pi))
            if line_text:
                extracted_lines.append(line_text)
            if line_visible:
                visible_lines.append(line_visible)

        return "\n".join(extracted_lines), "\n".join(visible_lines), issues

    def _run_text(self, run: etree._Element) -> str:
        parts: list[str] = []
        for t in run.iter(f"{{{_NS['w']}}}t"):
            if t.text:
                parts.append(t.text)
        return "".join(parts)

    @staticmethod
    def _is_visible_run(rpr: etree._Element | None) -> bool:
        if rpr is None:
            return True
        if rpr.find("w:vanish", _NS) is not None:
            return False
        if DOCXScanner._run_color(rpr) in NEAR_WHITE_COLORS:
            return False
        if DOCXScanner._run_size(rpr) <= TINY_HALF_POINTS:
            return False
        return True

    @staticmethod
    def _run_color(rpr: etree._Element) -> str | None:
        color = rpr.find("w:color", _NS) if rpr is not None else None
        if color is None:
            return None
        val = color.get(f"{{{_NS['w']}}}val")
        return val.lower() if val else None

    @staticmethod
    def _run_size(rpr: etree._Element) -> float:
        sz = rpr.find("w:sz", _NS) if rpr is not None else None
        if sz is None:
            return float("inf")
        val = sz.get(f"{{{_NS['w']}}}val")
        try:
            return float(val) if val else float("inf")
        except ValueError:
            return float("inf")

    def _run_issues(self, rpr: etree._Element | None, text: str, para_index: int) -> list[Issue]:
        out: list[Issue] = []
        if not text.strip():
            return out
        loc = {"paragraph": para_index}
        if rpr is None:
            return out

        if rpr.find("w:vanish", _NS) is not None:
            out.append(
                Issue(
                    code="ST-DOCX-HIDDEN-RUN",
                    severity="high",
                    message="Run marked with <w:vanish/> is hidden from the document view.",
                    evidence=text[:200],
                    location={**loc, "property": "vanish"},
                )
            )

        color = self._run_color(rpr)
        if color in NEAR_WHITE_COLORS:
            out.append(
                Issue(
                    code="ST-DOCX-WHITE-TEXT",
                    severity="high",
                    message="White / near-white run text is invisible on a light background.",
                    evidence=text[:200],
                    location={**loc, "color": color},
                )
            )

        size = self._run_size(rpr)
        if size <= TINY_HALF_POINTS:
            out.append(
                Issue(
                    code="ST-DOCX-TINY-TEXT",
                    severity="high",
                    message=f"Tiny run text (font size {size / 2:.2f}pt) is effectively invisible.",
                    evidence=text[:200],
                    location={**loc, "font_size_half_points": size},
                )
            )

        return out

    def _scan_comments(self, z: zipfile.ZipFile, names: list[str]) -> list[Issue]:
        issues: list[Issue] = []
        for part in names:
            if not (part.startswith("word/comment") and part.endswith(".xml")):
                continue
            tree = self._read_xml(z, part)
            if tree is None:
                continue
            for ci, comment in enumerate(tree.iter(f"{{{_NS['w']}}}comment")):
                text = "".join(
                    t.text or ""
                    for t in comment.iter(f"{{{_NS['w']}}}t")
                )
                if not text.strip():
                    continue
                general = TXTScanner().scan_text(text)
                if general.issues:
                    issues.append(
                        Issue(
                            code="ST-DOCX-COMMENT-PROMPT",
                            severity="high",
                            message="Prompt-like / encoded payload found in a document comment.",
                            evidence=text[:200],
                            location={"part": part, "comment_index": ci},
                        )
                    )
        return issues

    def _scan_headers_footers(self, z: zipfile.ZipFile, names: list[str]) -> list[Issue]:
        issues: list[Issue] = []
        for part in names:
            if not re.search(r"word/(header|footer)\d*\.xml$", part):
                continue
            tree = self._read_xml(z, part)
            if tree is None:
                continue
            root = tree.getroot()
            # Collect all text plus run-level formatting in this part.
            part_text = "".join(
                t.text or "" for t in root.iter(f"{{{_NS['w']}}}t")
            )
            if not part_text.strip():
                continue

            # Re-use the general detectors on the full header/footer text.
            general = TXTScanner().scan_text(part_text)
            has_general_issue = bool(general.issues)

            # Also check for hidden-run / white / tiny formatting local to the
            # header/footer, since that is where payloads are commonly hidden.
            has_format_issue = False
            for run in root.iter(f"{{{_NS['w']}}}r"):
                rpr = run.find("w:rPr", _NS)
                run_text = self._run_text(run)
                if not run_text.strip():
                    continue
                if not self._is_visible_run(rpr):
                    has_format_issue = True
                    break

            if has_general_issue or has_format_issue:
                issues.append(
                    Issue(
                        code="ST-DOCX-HEADER-FOOTER-PROMPT",
                        severity="high",
                        message="Hidden or prompt-like payload found in a header or footer.",
                        evidence=part_text[:200],
                        location={"part": part},
                    )
                )

            # Alt text on drawings in headers/footers.
            issues.extend(self._scan_alt_text(tree, part))
        return issues

    def _scan_metadata(self, metadata: dict[str, Any]) -> list[Issue]:
        issues: list[Issue] = []
        for key, value in metadata.items():
            text = value if isinstance(value, str) else str(value)
            general = TXTScanner().scan_text(text)
            if general.issues:
                issues.append(
                    Issue(
                        code="ST-DOCX-METADATA-PROMPT",
                        severity="high",
                        message=f"Prompt-like / encoded payload in DOCX metadata field {key}.",
                        evidence=text[:200],
                        location={"field": key},
                    )
                )
        return issues

    def _scan_alt_text(self, tree: etree._ElementTree, part: str) -> list[Issue]:
        """Scan drawing ``docPr`` elements for prompt-like / encoded payloads.

        In OOXML, images and drawings carry alt text in ``<wp:docPr>``
        elements via the ``descr`` (description) and ``title`` attributes.
        These are invisible in the rendered document but machine-readable.
        """
        issues: list[Issue] = []
        root = tree.getroot()
        for di, doc_pr in enumerate(root.iter(f"{{{_NS['wp']}}}docPr")):
            for attr_name in ("descr", "title"):
                val = doc_pr.get(attr_name)
                if not val or not val.strip():
                    continue
                general = TXTScanner().scan_text(val)
                if general.issues:
                    issues.append(
                        Issue(
                            code="ST-DOCX-ALT-TEXT-PROMPT",
                            severity="high",
                            message=f"Prompt-like / encoded payload in drawing alt-text '{attr_name}'.",
                            evidence=val[:200],
                            location={"part": part, "drawing_index": di, "attribute": attr_name},
                        )
                    )
        return issues

    @staticmethod
    def _read_xml(z: zipfile.ZipFile, name: str) -> etree._ElementTree | None:
        if name not in z.namelist():
            return None
        try:
            data = z.read(name)
            return etree.fromstring(data).getroottree()
        except (etree.XMLSyntaxError, KeyError, zipfile.BadZipFile):
            return None
