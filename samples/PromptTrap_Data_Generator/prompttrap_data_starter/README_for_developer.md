# PromptTrap data-generation starter

This is a small learning dataset generator for testing document-intake scanning.
It creates clean synthetic documents and intentionally manipulated synthetic documents with known labels.

It does not use real applicant data. It does not require paid APIs. It is only for local testing.

## Setup on Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts/generate_corpus.py --out data/generated --clean 20 --attacked 40 --seed 42
```

## Setup on macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts/generate_corpus.py --out data/generated --clean 20 --attacked 40 --seed 42
```

## Output

The generator creates:

```text
data/generated/
  clean/
  attacked/
  manifest.jsonl
  summary.json
```

Each row in `manifest.jsonl` is ground truth for one generated file.
The scanner should use this manifest to check whether it detected the expected issue.

## Supported formats

- PDF
- DOCX
- HTML
- TXT

## Attack examples included

- White text on white background
- Tiny text
- Off-page PDF text
- PDF metadata prompt
- DOCX comments
- DOCX metadata
- DOCX header/footer hidden text
- HTML comments
- HTML `display:none`
- HTML metadata
- HTML off-screen text
- HTML image alt text
- Zero-width Unicode text
- Base64-encoded test instruction

## Cross-platform notes

- The script uses `pathlib`, so paths work on Windows and macOS.
- Files are written with UTF-8 encoding.
- No shell scripts are required.
- Keep generated data out of Git unless the files are deliberately small.
- Commit the generator and manifest schema, not huge generated corpora.
