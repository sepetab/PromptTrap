"""Base scanner interface shared by all format scanners."""
from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Issue:
    """A single detected anomaly in a document."""

    code: str
    severity: str
    message: str
    evidence: str
    location: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    """Output of scanning one file."""

    path: str
    file_type: str
    sha256: str
    size_bytes: int
    issues: list[Issue] = field(default_factory=list)
    extracted_text: str = ""
    visible_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    processing_time_ms: float = 0.0

    @property
    def is_clean(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @property
    def issue_codes(self) -> list[str]:
        return sorted({i.code for i in self.issues})


class BaseScanner:
    """Common helpers for format scanners."""

    name = "base"

    def scan(self, path: Path) -> ScanResult:
        raise NotImplementedError

    @staticmethod
    def sha256_of(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def detect_type(path: Path) -> str:
        guess, _ = mimetypes.guess_type(str(path))
        if path.suffix.lower() == ".txt":
            return "text/plain"
        return guess or "application/octet-stream"
