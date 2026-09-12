"""HTML evidence report writer."""
from __future__ import annotations

import html
from pathlib import Path

from purifydocs.scanner.base import ScanResult


def render_html(result: ScanResult) -> str:
    rows = []
    for issue in result.issues:
        rows.append(
            "<tr>"
            f"<td>{html.escape(issue.code)}</td>"
            f"<td>{html.escape(issue.severity)}</td>"
            f"<td>{html.escape(issue.message)}</td>"
            f"<td><code>{html.escape(issue.evidence[:200])}</code></td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="4">No issues detected.</td></tr>')

    visible = html.escape(result.visible_text[:4000])
    extracted = html.escape(result.extracted_text[:4000])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PurifyDocs Evidence: {html.escape(result.path)}</title>
<style>
  body {{ font-family: sans-serif; margin: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }}
  th {{ background: #f0f0f0; }}
  pre {{ background: #f7f7f7; padding: 1rem; overflow-x: auto; white-space: pre-wrap; }}
  .clean {{ color: green; font-weight: bold; }}
  .dirty {{ color: #b00; font-weight: bold; }}
</style>
</head>
<body>
<h1>PurifyDocs Evidence Report</h1>
<p><strong>Path:</strong> <code>{html.escape(result.path)}</code></p>
<p><strong>SHA-256:</strong> <code>{result.sha256}</code></p>
<p><strong>Status:</strong>
   <span class="{'clean' if result.is_clean else 'dirty'}">
     {'CLEAN' if result.is_clean else 'ISSUES FOUND (' + str(len(result.issues)) + ')'}
   </span>
</p>
<p><strong>Processing time:</strong> {result.processing_time_ms} ms</p>

<h2>Issues</h2>
<table>
<tr><th>Code</th><th>Severity</th><th>Message</th><th>Evidence</th></tr>
{''.join(rows)}
</table>

<h2>Human-visible text</h2>
<pre>{visible}</pre>

<h2>Parser-extracted text (raw)</h2>
<pre>{extracted}</pre>
</body>
</html>
"""


def write_html_report(result: ScanResult, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "evidence.html"
    path.write_text(render_html(result), encoding="utf-8")
    return path
