# PurifyDocs

Document-safety scanner. Detects hidden or machine-readable manipulation in
PDF, DOCX, HTML, and TXT files, then emits clean, AI-readable output plus
evidence reports.

---

## Architecture

PurifyDocs is split into three components:

| Component | Tech | Hosting |
|----------|------|---------|
| **Frontend** | Static HTML/CSS/JS | Cloudflare Pages (free) |
| **API** | FastAPI + Python scanner | Northflank (free sandbox) or any Docker host |
| **CLI / library** | Python package | Local / Docker |

The frontend is a static site — no server process, served from Cloudflare's CDN.
The API runs the Python scanner (with native dependencies like Tesseract OCR) on
a container platform. The frontend talks to the API via CORS-enabled HTTP.

```
┌─────────────────────┐     HTTPS      ┌──────────────────────┐
│  Cloudflare Pages   │ ──────────────> │  API (Northflank)    │
│  apps/web/          │   POST /scan   │  apps/api/           │
│  static HTML/CSS/JS │ <────────────── │  FastAPI + scanner   │
└─────────────────────┘    JSON resp   └──────────────────────┘
```

---

## Quick start (local dev)

### Prerequisites

- Docker Desktop (with WSL2 on Windows)
- Or: Python 3.12+, `uv`, and system Tesseract OCR

### Docker Compose (recommended)

```bash
git clone <repo-url> purifydocs
cd purifydocs

# Start the API + Streamlit viewer
docker compose up --build api viewer

# Run tests
docker compose run --rm app pytest
docker compose run --rm app ruff check .

# Scan a file via CLI
docker compose run --rm app python -m purifydocs scan \
  "samples/PurifyDocs_Data_Generator/purifydocs_data_starter/data_sample/generated/attacked/attacked_0001_resume_pdf_white_text.pdf" \
  --out out/demo
```

- **API** at `http://localhost:8000` — FastAPI docs at `/docs`
- **Viewer** at `http://localhost:8501` — Streamlit web UI

### Frontend (static)

The static frontend in `apps/web/` can be opened directly in a browser for
local development. Edit `apps/web/js/config.js` to set `API_BASE_URL` to your
local or deployed API.

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Health check |
| `GET` | `/formats` | Supported file formats |
| `POST` | `/scan` | Upload a file → full scan report (JSON) |
| `POST` | `/scan/text` | Scan raw text → report (TXT scanner only) |
| `POST` | `/scan/html` | Upload a file → HTML evidence report |
| `POST` | `/scan/safe` | Upload a file → sanitized safe payload |
| `POST` | `/scan/full` | Upload a file → report + safe text + safe payload |
| `POST` | `/benchmark/generate` | Generate a synthetic test corpus |
| `POST` | `/benchmark/run` | Run benchmark on a generated corpus |

API documentation (OpenAPI/Swagger) is available at `/docs` when the server is
running.

---

## CLI commands

### Scan one file

```bash
docker compose run --rm app python -m purifydocs scan <file> --out <dir>
```

Writes an output folder containing:

| File | Contents |
|------|----------|
| `report.json` | Issue list, hashes, metadata, processing time |
| `evidence.html` | Human-readable evidence report |
| `safe_text.txt` | Sanitized plain text with detected payloads removed |
| `safe_payload.json` | Structured payload: source/safe SHA-256, issue summary, safe text |

### Benchmark

```bash
docker compose run --rm app python -m purifydocs benchmark generate --clean 150 --attacked 150
docker compose run --rm app python -m purifydocs benchmark run \
  --input data/generated --out reports/benchmark.json
```

---

## Tests

```bash
docker compose run --rm app pytest
docker compose run --rm app ruff check .
```

---

## Deployment

### Frontend → Cloudflare Pages

1. Push this repo to GitHub.
2. In Cloudflare Pages, create a project connected to the repo.
3. Set build output directory to `apps/web/`.
4. No build command needed — it's static HTML/CSS/JS.
5. After deployment, edit `apps/web/js/config.js` and set `API_BASE_URL` to
   your deployed API URL.

Alternatively, use the `wrangler.toml` config:

```bash
npx wrangler pages deploy apps/web
```

### API → Northflank

1. Create a free Northflank Developer Sandbox account.
2. Create a new service from the Dockerfile in this repo (connect your Git
   repo or use the Docker image directly).
3. Set the run command to:
   ```
   uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
   ```
4. Northflank will build and run the container with all native dependencies
   (Tesseract OCR, etc.) included.
5. Copy the deployed API URL and update `apps/web/js/config.js`.

### API → Any Docker host

The same Docker image works on Fly.io, Railway, Render, a VPS, or any
container platform:

```bash
docker build -t purifydocs .
docker run -p 8000:8000 purifydocs uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

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
purifydocs/
  purifydocs/scanner/    PDF, DOCX, HTML, TXT scanners + content detection
  purifydocs/sanitizer/  safe_text and safe_payload generation
  purifydocs/benchmark/  generator, attack seeder, metrics
  purifydocs/reports/    JSON/HTML evidence reports
  apps/api/             FastAPI backend (scan, benchmark endpoints)
  apps/web/             Static frontend for Cloudflare Pages
  apps/viewer/          Streamlit viewer (local dev alternative)
  samples/              clean + attacked examples
  tests/                pytest unit and integration tests
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
