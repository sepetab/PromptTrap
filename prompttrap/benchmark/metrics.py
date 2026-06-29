"""metrics: recall, false positives, sanitization leakage, preservation, crash rate."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prompttrap.scanner import scan as run_scan
from prompttrap.sanitizer.safe_text import safe_text
from prompttrap.scanner.txt import TXTScanner


def run_benchmark(corpus_dir: Path) -> dict[str, Any]:
    """Scan every file referenced in corpus_dir/manifest.jsonl and score."""
    corpus_dir = Path(corpus_dir)
    manifest_path = corpus_dir / "manifest.jsonl"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    tp = fp = fn = tn = crashed = 0
    leakage_hits = 0
    preservation_scores: list[float] = []
    timings: list[float] = []
    per_case: list[dict[str, Any]] = []

    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        rel = entry["path"]
        doc_path = corpus_dir.parent.parent / rel if not Path(rel).is_absolute() else Path(rel)
        if not doc_path.is_file():
            doc_path = corpus_dir / Path(rel).name

        expected = entry.get("expected_issue_codes", []) or []
        expected_attack = entry.get("label") == "attacked"

        try:
            result = run_scan(doc_path)
            detected = set(result.issue_codes)
            predicted_attack = bool(result.issue_codes)
            timings.append(result.processing_time_ms)

            if predicted_attack and expected_attack:
                tp += 1
            elif predicted_attack and not expected_attack:
                fp += 1
            elif not predicted_attack and expected_attack:
                fn += 1
            else:
                tn += 1

            # sanitization leakage: re-scan the cleaned text
            clean = safe_text(result)
            rescan = TXTScanner().scan_text(clean)
            if rescan.issues:
                leakage_hits += 1

            # visible-content preservation: ratio of visible chars to original
            if result.extracted_text:
                ratio = len(result.visible_text) / max(1, len(result.extracted_text))
                preservation_scores.append(ratio)

            per_case.append({"case_id": entry["case_id"], "detected": sorted(detected)})
        except Exception as e:
            crashed += 1
            per_case.append({"case_id": entry.get("case_id"), "error": str(e)})

    total = tp + fp + fn + tn
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fp_rate = fp / (fp + tn) if (fp + tn) else 0.0
    return {
        "total": total,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "crashes": crashed,
        "recall": round(recall, 4),
        "false_positive_rate": round(fp_rate, 4),
        "sanitization_leakage": leakage_hits,
        "preservation": round(sum(preservation_scores) / len(preservation_scores), 4)
        if preservation_scores
        else 0.0,
        "crash_rate": round(crashed / total, 4) if total else 0.0,
        "avg_processing_ms": round(sum(timings) / len(timings), 3) if timings else 0.0,
        "per_case": per_case,
    }
