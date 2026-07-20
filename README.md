# PromptTrap

Local-first document-safety scanner. Detects hidden or machine-readable
manipulation in PDF, DOCX, HTML, and TXT files, then emits clean, AI-readable
output plus evidence reports.

This is a learning project / MVP. No accounts, no external integrations, no
paid APIs. See `PromptTrap_MVP_Windows_First_Learning_Handoff.pdf` for the full
spec.

---

## Quick start

The official run path is Docker Compose, identical on Windows/WSL2 and macOS.

### Windows / WSL2

Requirements: Git for Windows, VS Code, Docker Desktop with WSL integration,
WSL2 Ubuntu.

```bash
mkdir -p ~/code && cd ~/code
git clone <repo-url> prompttrap
cd prompttrap
docker compose up --build
docker compose run --rm app pytest
docker compose run --rm app python -m prompttrap scan \
  "samples/PromptTrap_Data_Generator/prompttrap_data_starter/data_sample/generated/attacked/attacked_0001_resume_pdf_white_text.pdf" \
  --out out/demo
```

> Keep the repo inside the WSL Linux filesystem (`~/code/promptrap`), not in
> `C:\Users\...` or OneDrive, for filesystem performance and line-ending sanity.

### macOS

```bash
git clone <repo-url> prompttrap
cd prompttrap
docker compose up --build
docker compose run --rm app pytest
```

The same Docker Compose commands work — no platform-specific setup.

---

## Commands

### Scan one file

```bash
docker compose run --rm app python -m prompttrap scan <file> --out <dir>
```

Writes an output folder containing:

| File | Contents |
|------|----------|
| `report.json` | Issue list, hashes, metadata, processing time |
| `evidence.html` | Human-readable evidence report |
| `safe_text.txt` | Sanitized plain text with detected payloads removed |
| `safe_payload.json` | Structured payload: source/safe SHA-256, issue summary, safe text |

The CLI prints the original SHA-256, detected issue codes, and a leakage count
(the re-scanned safe output must contain zero seeded payloads).

### Benchmark

Generate a synthetic corpus, then score the scanner over it:

```bash
docker compose run --rm app python -m prompttrap benchmark generate --clean 150 --attacked 150
docker compose run --rm app python -m prompttrap benchmark run \
  --input data/generated --out reports/benchmark.json
```

`benchmark generate` creates clean and attacked PDF/DOCX/HTML/TXT files with a
`manifest.jsonl` recording the ground-truth label and expected issue codes for
each case. `benchmark run` scans every manifest entry and reports recall, false
positives, sanitization leakage, content preservation, crash rate, and timing.

---

## Tests

```bash
docker compose run --rm app pytest
docker compose run --rm app ruff check .
```

Tests are split into unit tests per scanner (`tests/test_scanner_*.py`), content
detection tests (`tests/test_detect.py`), and end-to-end integration tests
(`tests/test_integration.py`) that exercise the bundled sample corpus.

---

## Streamlit viewer

A web-based viewer for scanning files and browsing benchmark metrics:

```bash
docker compose up viewer
```

Open `http://localhost:8501` in your browser. The viewer has three pages:

- **Home** — overview of what PromptTrap does, how to use the viewer, supported
  formats and detectors, and CLI command reference.
- **Scan** — upload a PDF/DOCX/HTML/TXT file, run the scanner, and view:
  - Summary metrics (issue count, file type, size, scan time)
  - Downloadable reports (markdown summary, full JSON report, sanitized safe text)
  - Detected issues with severity, code, location, and evidence
  - Visible vs extracted text side-by-side comparison
  - Sanitized safe text and metadata
  - Recent scans list — click **View** to reload any past scan result
- **Benchmark** — load an existing benchmark JSON report, upload one, or generate
  a new benchmark inline. Dashboard shows metric cards (recall, FP rate, leakage,
  preservation, crash rate), target compliance with pass/fail indicators,
  confusion matrix, and per-case breakdown.

---

## How it works

1. **Hash** the original file (SHA-256).
2. **Detect type by content** — magic bytes and zip structure, not the file
   extension. A PDF renamed `.txt` is still scanned as a PDF.
3. **Extract** machine-readable text, coordinates, metadata, comments,
   annotations, alt text, and encoded strings.
4. **Render/OCR** where practical to approximate the human-visible view.
5. **Compare** OCR/visible text against parser-extracted text and flag
   mismatches.
6. **Apply deterministic rules** for hidden text, Unicode tricks, metadata
   prompts, base64 payloads, and prompt-like language.
7. **Generate** `safe_text.txt` and `safe_payload.json`, then re-scan the safe
   output to confirm seeded payloads are gone.

### Supported formats and detectors

#### PDF (`pdfminer.six`, `pypdf`, `pypdfium2`, `pytesseract`)

| Code | Detects |
|------|---------|
| `ST-PDF-HIDDEN-TEXT-WHITE` | White / near-white text invisible on the page |
| `ST-PDF-TINY-TEXT` | Font size too small to be human-visible |
| `ST-PDF-OFFPAGE-TEXT` | Text drawn outside the page media box |
| `ST-PDF-METADATA-PROMPT` | Prompt-like / base64 payload in PDF metadata |
| `ST-PDF-ANNOTATION-PROMPT` | Prompt-like / base64 payload in PDF annotations (`/Contents`, `/T`, `/RC`) |
| `ST-PDF-OCR-MISMATCH` | OCR text differs substantially from extracted text |

#### DOCX (`zipfile`, `lxml`)

| Code | Detects |
|------|---------|
| `ST-DOCX-WHITE-TEXT` | White / near-white run text (`<w:color w:val="FFFFFF"/>`) |
| `ST-DOCX-TINY-TEXT` | Tiny run text (font size below threshold) |
| `ST-DOCX-HIDDEN-RUN` | Run marked with `<w:vanish/>` |
| `ST-DOCX-COMMENT-PROMPT` | Prompt-like / encoded payload in document comments |
| `ST-DOCX-HEADER-FOOTER-PROMPT` | Hidden or prompt-like payload in headers/footers |
| `ST-DOCX-METADATA-PROMPT` | Prompt-like / encoded payload in core metadata |
| `ST-DOCX-ALT-TEXT-PROMPT` | Payload in drawing alt text (`<wp:docPr descr="...">`) |

#### HTML (`beautifulsoup4`, `lxml`, `tinycss2`)

| Code | Detects |
|------|---------|
| `ST-HTML-HIDDEN-DISPLAY` | Element hidden with `display:none` (inline or `<style>` block) |
| `ST-HTML-HIDDEN-VISIBILITY` | Element hidden with `visibility:hidden` |
| `ST-HTML-HIDDEN-OPACITY` | Element hidden with `opacity:0` |
| `ST-HTML-WHITE-TEXT` | White / near-white text on light background |
| `ST-HTML-TINY-TEXT` | Tiny font-size text |
| `ST-HTML-OFFSCREEN-TEXT` | Text positioned off-screen via large negative offsets |
| `ST-HTML-COMMENT-PROMPT` | Prompt-like / encoded payload in HTML comments |
| `ST-HTML-METADATA-PROMPT` | Payload in `<meta>` tags or `<title>` |
| `ST-HTML-ALT-TEXT-PROMPT` | Payload in `alt` / `title` attributes |

CSS inheritance is resolved by walking ancestor `<style>` block rules and inline
styles, so class-based hiding (`.hidden { display:none }`) and hidden parents
are both detected.

#### General (applied to all formats via `TXTScanner`)

| Code | Detects |
|------|---------|
| `ST-GEN-ZERO-WIDTH` | Zero-width Unicode characters (ZWSP, ZWNJ, ZWJ, WJ, BOM) hiding text |
| `ST-GEN-BASE64-INSTRUCTION` | Base64-encoded instruction payload |
| `ST-GEN-PROMPT-LIKE-INSTRUCTION` | Prompt-injection phrasing in document text |

---

## Benchmark results (300-file corpus)

| Metric | Target | Actual |
|--------|--------|--------|
| Seeded attack recall | >= 90% | 100% |
| False positives on clean docs | <= 3% | 0% |
| Sanitization leakage | 0 | 0 |
| Visible content preservation | >= 95% | 95.2% |
| Crash rate | <= 1% | 0% |

---

## Repository layout

```
promptrap/
  prompttrap/scanner/    PDF, DOCX, HTML, TXT scanners + content detection
  prompttrap/sanitizer/  safe_text and safe_payload generation
  prompttrap/benchmark/  generator, attack seeder, metrics
  prompttrap/reports/    JSON/HTML evidence reports
  samples/               clean + attacked examples
  tests/                 pytest unit and integration tests
  apps/viewer/           Streamlit viewer (scan, benchmark, home)
```

---

## Known limitations

- OCR mismatch detection is PDF-only and best-effort; it depends on Tesseract
  and degrades silently (no issue raised) if rendering or OCR fails. DOCX/HTML
  OCR mismatch is not implemented.
- Zero-width Unicode characters in PDFs may be dropped by the PDF font and
  surface only as prompt-like text rather than as a zero-width issue.
- LibreOffice is installed in Docker but not yet used for DOCX-to-PDF rendering.
- The CLI re-scan for leakage uses the TXT scanner on `safe_text.txt` output,
  which is always plain text regardless of input format.

## Next steps

1. Add DOCX-to-PDF rendering via LibreOffice for OCR mismatch detection on DOCX.
2. Clean up unused dependencies (`pikepdf`, `regex` module).
3. Improve `metrics.py` path resolution to be corpus-root-relative.
