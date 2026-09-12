"""JSON evidence report writer."""
from __future__ import annotations

import json
from pathlib import Path

from purifydocs.scanner.base import ScanResult


def to_report_dict(result: ScanResult) -> dict:
    return {
        "path": result.path,
        "file_type": result.file_type,
        "sha256": result.sha256,
        "size_bytes": result.size_bytes,
        "is_clean": result.is_clean,
        "issue_count": len(result.issues),
        "issue_codes": result.issue_codes,
        "issues": [i.to_dict() for i in result.issues],
        "processing_time_ms": result.processing_time_ms,
        "metadata": result.metadata,
        "visible_text": result.visible_text,
        "extracted_text": result.extracted_text,
    }


def write_json_report(result: ScanResult, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "report.json"
    path.write_text(
        json.dumps(to_report_dict(result), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
