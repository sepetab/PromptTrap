"""safe_payload: structured payload safe to feed downstream LLMs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from prompttrap.scanner.base import ScanResult
from prompttrap.sanitizer.safe_text import safe_text


def safe_payload(result: ScanResult) -> dict[str, Any]:
    """Build the structured safe payload dict.

    Includes original hash, safe hash, issue summary, and sanitized text.
    """
    clean = safe_text(result)
    safe_hash = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    return {
        "source_path": result.path,
        "source_sha256": result.sha256,
        "safe_sha256": safe_hash,
        "file_type": result.file_type,
        "is_clean": result.is_clean,
        "issue_codes": result.issue_codes,
        "issue_count": len(result.issues),
        "processing_time_ms": result.processing_time_ms,
        "safe_text": clean,
    }


def write_safe_outputs(result: ScanResult, out_dir: Path) -> dict[str, Path]:
    """Write safe_text.txt and safe_payload.json to out_dir.

    Returns a mapping of output name -> path.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = safe_text(result)
    text_path = out_dir / "safe_text.txt"
    text_path.write_text(clean, encoding="utf-8")

    payload = safe_payload(result)
    payload_path = out_dir / "safe_payload.json"
    payload_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {"safe_text": text_path, "safe_payload": payload_path}
