"""PurifyDocs API — FastAPI backend wrapping the document scanner.

Endpoints:
  GET  /                   Health check + version info
  GET  /formats            Supported file formats
  POST /scan               Upload a file, get full scan report (JSON)
  POST /scan/text          Scan raw text (TXT scanner only)
  POST /scan/html          Upload a file, get HTML evidence report
  POST /scan/safe          Upload a file, get sanitized safe payload
  POST /benchmark/generate Generate a synthetic benchmark corpus
  POST /benchmark/run      Run benchmark on a generated corpus

Run locally:
    uvicorn apps.api.main:app --reload

Run via Docker Compose:
    docker compose up api
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from purifydocs.reports.html_report import render_html
from purifydocs.reports.json_report import to_report_dict
from purifydocs.sanitizer.safe_payload import safe_payload
from purifydocs.sanitizer.safe_text import safe_text
from purifydocs.scanner import scan as run_scan
from purifydocs.scanner.detect import DOCX, HTML, PDF, TXT
from purifydocs.scanner.txt import TXTScanner

app = FastAPI(
    title="PurifyDocs API",
    description="Document-safety scanner — detect hidden manipulation in PDF, DOCX, HTML, and TXT files.",
    version="0.1.0",
)

_ALLOWED_ORIGINS = [
    "http://localhost:8501",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://purifydocs.pages.dev",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _scan_upload(upload: UploadFile) -> Any:
    """Save upload to a temp file, scan it, and return the ScanResult."""
    content = upload.file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB).")

    suffix = Path(upload.filename or "").suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        return run_scan(tmp_path)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/")
def health() -> dict[str, str]:
    return {"status": "ok", "name": "PurifyDocs API", "version": "0.1.0"}


@app.get("/formats")
def formats() -> dict[str, list[str]]:
    return {
        "supported": [PDF, DOCX, HTML, TXT],
        "extensions": ["pdf", "docx", "html", "htm", "txt"],
    }


@app.post("/scan")
async def scan_file(file: UploadFile = File(...)) -> dict[str, Any]:
    result = _scan_upload(file)
    return to_report_dict(result)


@app.post("/scan/text")
def scan_text(body: str = Form(...)) -> dict[str, Any]:
    if len(body) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Input too large (max 50 MB).")
    result = TXTScanner().scan_text(body)
    return to_report_dict(result)


@app.post("/scan/html", response_class=HTMLResponse)
def scan_html(file: UploadFile = File(...)) -> str:
    result = _scan_upload(file)
    return render_html(result)


@app.post("/scan/safe")
def scan_safe(file: UploadFile = File(...)) -> dict[str, Any]:
    result = _scan_upload(file)
    return safe_payload(result)


@app.post("/scan/full")
async def scan_full(file: UploadFile = File(...)) -> dict[str, Any]:
    """Return both the scan report and safe payload in one response."""
    result = _scan_upload(file)
    report = to_report_dict(result)
    payload = safe_payload(result)
    return {
        "report": report,
        "safe_payload": payload,
        "safe_text": safe_text(result),
    }


@app.post("/benchmark/generate")
def benchmark_generate(
    clean: int = Form(150),
    attacked: int = Form(150),
    seed: int = Form(42),
) -> dict[str, Any]:
    from purifydocs.benchmark.generate_corpus import generate

    out_dir = Path("data/generated")
    generate(out_dir, clean, attacked, seed)

    summary_path = out_dir / "summary.json"
    import json

    summary: dict[str, Any] = {}
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["output_dir"] = str(out_dir)
    return summary


@app.post("/benchmark/run")
def benchmark_run(input_dir: str = Form("data/generated")) -> dict[str, Any]:
    from purifydocs.benchmark.metrics import run_benchmark

    corpus = Path(input_dir)
    if not corpus.exists():
        raise HTTPException(status_code=404, detail=f"Corpus not found: {input_dir}")
    try:
        return run_benchmark(corpus)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
