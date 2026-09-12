"""TXT scanner: extracts raw text and detects manipulation.

Detectors:
  * zero-width Unicode characters (ZWSP, ZWNJ, ZWJ, WJ, BOM)
  * Base64-like instruction payloads
  * prompt-like instructions
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from purifydocs.scanner.base import BaseScanner, Issue, ScanResult

# Zero-width / invisible characters that hide text from human eyes.
ZERO_WIDTH_CHARS = {
    "\u200b": "ZWSP (zero-width space)",
    "\u200c": "ZWNJ (zero-width non-joiner)",
    "\u200d": "ZWJ (zero-width joiner)",
    "\u2060": "WJ (word joiner)",
    "\ufeff": "BOM / ZWNBSP",
}

# Base64 token: long runs of base64 alphabet chars, min length 40.
BASE64_RE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")

# Prompt-instruction phrasing. Case-insensitive.
PROMPT_LIKE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore (all )?previous instructions",
        r"disregard (all )?previous (instructions|prompts)",
        r"system prompt",
        r"reveal your (system )?prompt",
        r"test payload only",
        r"do not mention",
        r"hidden note says",
        r"act as (if )?a ",
        r"new instructions:",
        r"override (your )?instructions",
    )
]

PROMPT_LIKE_TRIGGERS = [
    "ignore previous instructions",
    "system prompt",
    "test payload only",
    "do not mention",
    "hidden note says",
]


class TXTScanner(BaseScanner):
    name = "txt"

    def scan(self, path: Path) -> ScanResult:
        path = Path(path)
        start = time.perf_counter()
        sha = self.sha256_of(path)
        raw_bytes = path.read_bytes()
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        result = self.scan_text(raw_text)
        result.path = str(path)
        result.file_type = self.detect_type(path)
        result.sha256 = sha
        result.size_bytes = len(raw_bytes)
        result.processing_time_ms = result.processing_time_ms or round(
            (time.perf_counter() - start) * 1000, 3
        )
        return result

    def scan_text(self, text: str) -> ScanResult:
        """Scan an in-memory string. Used for re-scanning sanitized output."""
        start = time.perf_counter()
        issues: list[Issue] = []
        issues.extend(self._detect_zero_width(text, Path("<text>")))
        issues.extend(self._detect_base64(text))
        issues.extend(self._detect_prompt_like(text))
        visible = self._strip_zero_width(text)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ScanResult(
            path="<text>",
            file_type="text/plain",
            sha256="",
            size_bytes=len(text.encode("utf-8", errors="replace")),
            issues=issues,
            extracted_text=text,
            visible_text=visible,
            metadata={"lines": text.count("\n") + 1},
            processing_time_ms=round(elapsed_ms, 3),
        )

    def _detect_zero_width(self, text: str, path: Path) -> list[Issue]:
        issues: list[Issue] = []
        if not any(c in text for c in ZERO_WIDTH_CHARS):
            return issues

        present = [name for c, name in ZERO_WIDTH_CHARS.items() if c in text]
        zw_class = "".join(re.escape(c) for c in ZERO_WIDTH_CHARS)

        # Find contiguous spans of text that contain zero-width chars,
        # stopping at whitespace/newlines. Each span -> one issue.
        span_re = re.compile(rf"[^{zw_class}\s]+(?:[{zw_class}]+[^{zw_class}\s]*)+")
        found_any = False
        for m in span_re.finditer(text):
            snippet = self._strip_zero_width(m.group(0))
            if not snippet:
                continue
            found_any = True
            issues.append(
                Issue(
                    code="ST-GEN-ZERO-WIDTH",
                    severity="high",
                    message=(
                        "Zero-width Unicode characters hide text from human view: "
                        + ", ".join(present)
                    ),
                    evidence=snippet[:200],
                    location={"start": m.start(), "end": m.end()},
                )
            )

        if not found_any:
            issues.append(
                Issue(
                    code="ST-GEN-ZERO-WIDTH",
                    severity="medium",
                    message="Stray zero-width Unicode characters present: " + ", ".join(present),
                    evidence="",
                    location={},
                )
            )
        return issues

    def _detect_base64(self, text: str) -> list[Issue]:
        issues: list[Issue] = []
        for m in BASE64_RE.finditer(text):
            token = m.group(0)
            decoded = self._try_decode_base64(token)
            if decoded is None:
                continue
            issues.append(
                Issue(
                    code="ST-GEN-BASE64-INSTRUCTION",
                    severity="high",
                    message="Base64-encoded payload decodes to instruction text.",
                    evidence=decoded[:200],
                    location={"start": m.start(), "end": m.end()},
                )
            )
        return issues

    def _detect_prompt_like(self, text: str) -> list[Issue]:
        issues: list[Issue] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            for pat in PROMPT_LIKE_PATTERNS:
                m = pat.search(line)
                if m:
                    issues.append(
                        Issue(
                            code="ST-GEN-PROMPT-LIKE-INSTRUCTION",
                            severity="high",
                            message="Prompt-like instruction found in document text.",
                            evidence=line.strip()[:200],
                            location={"line": line_no, "match_start": m.start()},
                        )
                    )
                    break
        return issues

    @staticmethod
    def _strip_zero_width(text: str) -> str:
        for c in ZERO_WIDTH_CHARS:
            text = text.replace(c, "")
        return text

    @staticmethod
    def _try_decode_base64(token: str) -> str | None:
        import base64

        try:
            raw = base64.b64decode(token, validate=True)
        except Exception:
            return None
        decoded = raw.decode("utf-8", errors="replace")
        if not decoded.isprintable() and " " not in decoded:
            return None
        return decoded
