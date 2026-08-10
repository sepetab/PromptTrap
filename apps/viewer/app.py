"""PromptTrap Streamlit viewer.

Two pages:
  * Scan   — upload a document, run the scanner, view issues, evidence,
             and visible vs extracted text side-by-side.
  * Benchmark — load a benchmark JSON report and display metrics dashboard.

Run locally:
    streamlit run apps/viewer/app.py

Run via Docker Compose:
    docker compose run --rm --service-ports app streamlit run apps/viewer/app.py --server.port=8501
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

from prompttrap.scanner import scan as run_scan
from prompttrap.sanitizer.safe_text import safe_text

st.set_page_config(page_title="PromptTrap", page_icon=":shield:", layout="wide")

# Lighter, more welcoming theme via injected CSS.
st.markdown("""
<style>
/* Soft, light theme */
.stApp {
    background-color: #eef1f5;
}
[data-testid="stSidebar"] {
    background-color: #dde4ec;
}
.stMetric {
    background-color: #ffffff;
    border-radius: 8px;
    padding: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


def _issue_color(severity: str) -> str:
    return {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")


def _diff_highlight(visible: str, extracted: str, max_chars: int = 8000) -> tuple[str, str]:
    """Return (visible_html, extracted_html) with extracted-only text highlighted.

    Uses difflib to find lines present in extracted but not in visible, and
    wraps them in a red highlight span so the user can see exactly what was
    hidden from the human view.
    """
    import html as html_mod

    visible_lines = visible[:max_chars].splitlines(keepends=True)
    extracted_lines = extracted[:max_chars].splitlines(keepends=True)
    visible_set = set(line.strip() for line in visible_lines if line.strip())

    vis_out = html_mod.escape("".join(visible_lines))
    ext_parts: list[str] = []

    for line in extracted_lines:
        escaped = html_mod.escape(line)
        if line.strip() and line.strip() not in visible_set:
            ext_parts.append(
                f'<span style="background-color:#ffcdd2;color:#b71c1c;'
                f'padding:1px 3px;border-radius:3px;font-weight:600;">{escaped}</span>'
            )
        else:
            ext_parts.append(escaped)

    return vis_out, "".join(ext_parts)


# ---------------------------------------------------------------------------
# Scan page
# ---------------------------------------------------------------------------


def render_scan_page() -> None:
    st.header("Scan a Document")
    st.caption("Upload a PDF, DOCX, HTML, or TXT file to scan for hidden manipulation.")

    uploaded = st.file_uploader(
        "Choose a file",
        type=["pdf", "docx", "html", "htm", "txt"],
        label_visibility="collapsed",
    )

    # Process a new upload — but only once per file (avoid rerun loop).
    if uploaded is not None and st.session_state.get("last_uploaded_name") != uploaded.name:
        st.session_state["last_uploaded_name"] = uploaded.name
        suffix = Path(uploaded.name).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = Path(tmp.name)

        try:
            with st.spinner("Scanning… this may take a few seconds for large PDFs."):
                result = run_scan(tmp_path)
        except Exception as exc:
            st.error(f"Scan failed: {exc}")
            tmp_path.unlink(missing_ok=True)
            _show_recent_scans()
            return
        finally:
            tmp_path.unlink(missing_ok=True)

        # Persist the scan to out/ so it appears in recent scans and survives
        # reruns / reconnects.
        _save_scan_to_out(uploaded.name, result)
        st.session_state["scan_result"] = result
        st.session_state["scan_filename"] = uploaded.name
        st.rerun()

    # Clear the dedup flag when the uploader is cleared.
    if uploaded is None:
        st.session_state.pop("last_uploaded_name", None)

    # If a result is in session state (from upload or recent-scan click),
    # render it.
    if "scan_result" in st.session_state:
        _render_scan_result(st.session_state["scan_filename"], st.session_state["scan_result"])
        if st.button("← Back to scan list", key="back_to_scans"):
            st.session_state.pop("scan_result", None)
            st.session_state.pop("scan_filename", None)
            st.rerun()
        return

    # No result loaded — show the upload + recent scans list.
    _show_recent_scans()


def _save_scan_to_out(filename: str, result: Any) -> None:
    """Persist a scan result to out/<name>/ with all report files."""
    from prompttrap.reports.json_report import write_json_report
    from prompttrap.reports.html_report import write_html_report
    from prompttrap.sanitizer.safe_payload import write_safe_outputs

    stem = Path(filename).stem
    out_dir = Path("out") / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json_report(result, out_dir)
    write_html_report(result, out_dir)
    write_safe_outputs(result, out_dir)


def _build_summary_markdown(filename: str, result: Any) -> str:
    """Build a human-readable markdown summary of a scan result."""
    lines = [
        "# PromptTrap Scan Report",
        "",
        f"**File:** `{filename}`",
        f"**File type:** {result.file_type}",
        f"**SHA-256:** `{result.sha256}`",
        f"**Size:** {_format_bytes(result.size_bytes)}",
        f"**Scan time:** {result.processing_time_ms:.0f} ms",
        f"**Result:** {'CLEAN — no issues detected' if result.is_clean else f'{len(result.issues)} issue(s) detected'}",
        "",
        "---",
        "",
    ]

    if result.issues:
        lines.append("## Detected Issues")
        lines.append("")
        lines.append("| # | Severity | Code | Message |")
        lines.append("|---|----------|------|---------|")
        for i, issue in enumerate(result.issues, 1):
            lines.append(f"| {i} | {issue.severity} | `{issue.code}` | {issue.message} |")
        lines.append("")

        lines.append("## Issue Details")
        lines.append("")
        for i, issue in enumerate(result.issues, 1):
            lines.append(f"### {i}. {issue.code}")
            lines.append(f"- **Severity:** {issue.severity}")
            lines.append(f"- **Message:** {issue.message}")
            if issue.location:
                loc_str = ", ".join(f"{k}: {v}" for k, v in issue.location.items())
                lines.append(f"- **Location:** {loc_str}")
            lines.append("- **Evidence:**")
            lines.append("  ```")
            lines.append(f"  {issue.evidence[:500]}")
            lines.append("  ```")
            lines.append("")
    else:
        lines.append("No issues detected. The document appears clean.")
        lines.append("")

    if len(result.extracted_text) > len(result.visible_text):
        delta = len(result.extracted_text) - len(result.visible_text)
        lines.append("## Text Comparison")
        lines.append(f"- **Visible text length:** {len(result.visible_text)} chars")
        lines.append(f"- **Extracted text length:** {len(result.extracted_text)} chars")
        lines.append(f"- **Difference:** {delta} chars (hidden content suspected)")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by PromptTrap — local-first document-safety scanner.*")

    return "\n".join(lines)


def _render_scan_result(filename: str, result: Any) -> None:
    st.subheader(f"Results: {filename}")

    # Summary metrics row.
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Issues", len(result.issues))
    col2.metric("File Type", result.file_type.split("/")[-1])
    col3.metric("Size", _format_bytes(result.size_bytes))
    col4.metric("Scan Time", f"{result.processing_time_ms:.0f} ms")

    st.divider()

    # Status banner.
    if result.is_clean:
        st.success("✅ No issues detected — document appears clean.")
    else:
        st.warning(f"⚠️ {len(result.issues)} issue(s) detected.")

    st.code(f"SHA-256: {result.sha256}", language="text")

    # Download buttons for the full report.
    st.subheader("Download Report")
    from prompttrap.reports.json_report import to_report_dict

    report_dict = to_report_dict(result)
    report_json = json.dumps(report_dict, indent=2, ensure_ascii=False)
    summary_md = _build_summary_markdown(filename, result)
    clean_text = safe_text(result)

    col_dl1, col_dl2, col_dl3 = st.columns(3)
    col_dl1.download_button(
        label="📄 Summary (.md)",
        data=summary_md,
        file_name=f"{Path(filename).stem}_summary.md",
        mime="text/markdown",
    )
    col_dl2.download_button(
        label="📋 Full Report (.json)",
        data=report_json,
        file_name=f"{Path(filename).stem}_report.json",
        mime="application/json",
    )
    col_dl3.download_button(
        label="🛡️ Safe Text (.txt)",
        data=clean_text,
        file_name=f"{Path(filename).stem}_safe_text.txt",
        mime="text/plain",
    )

    # Issue table.
    if result.issues:
        st.subheader("Detected Issues")
        for issue in result.issues:
            with st.expander(
                f"{_issue_color(issue.severity)} {issue.code} — {issue.message}",
                expanded=False,
            ):
                st.markdown(f"**Severity:** {issue.severity}")
                st.markdown(f"**Code:** `{issue.code}`")
                if issue.location:
                    loc_str = ", ".join(f"{k}: {v}" for k, v in issue.location.items())
                    st.markdown(f"**Location:** {loc_str}")
                st.markdown("**Evidence:**")
                st.code(issue.evidence[:500], language="text")

    # Visible vs extracted text comparison with hidden content highlighted.
    st.subheader("Human-Visible vs Machine-Extracted Text")
    col_vis, col_ext = st.columns(2)

    vis_html, ext_html = _diff_highlight(result.visible_text, result.extracted_text)

    with col_vis:
        st.markdown("**Visible Text** (what a human sees)")
        st.markdown(
            f'<div style="height:300px; overflow-y:auto; '
            f'border:1px solid #e0e0e0; border-radius:6px; padding:10px; '
            f'font-family:monospace; font-size:13px; white-space:pre-wrap; '
            f'background:#ffffff;">{vis_html or "(empty)"}</div>',
            unsafe_allow_html=True,
        )

    with col_ext:
        st.markdown("**Extracted Text** (machine-readable) — highlighted = hidden from humans")
        st.markdown(
            f'<div style="height:300px; overflow-y:auto; '
            f'border:1px solid #e0e0e0; border-radius:6px; padding:10px; '
            f'font-family:monospace; font-size:13px; white-space:pre-wrap; '
            f'background:#ffffff;">{ext_html or "(empty)"}</div>',
            unsafe_allow_html=True,
        )

    if len(result.extracted_text) > len(result.visible_text):
        delta = len(result.extracted_text) - len(result.visible_text)
        st.info(
            f"Extracted text is {delta} characters longer than visible text — "
            f"hidden content may be present."
        )

    # Sanitized output.
    st.subheader("Sanitized Safe Text")
    st.text_area("safe", value=clean_text[:8000], height=200, label_visibility="collapsed")

    # Metadata.
    if result.metadata:
        st.subheader("Metadata")
        st.json(result.metadata)


def _show_recent_scans() -> None:
    """Show existing scan reports from the out/ directory.

    Clicking a scan reloads its full result page via session_state.
    """
    out_dir = Path("out")
    if not out_dir.is_dir():
        st.subheader("Recent Scans")
        st.caption("No scans yet. Upload a file above to begin.")
        return
    reports = sorted(out_dir.glob("*/report.json"), reverse=True)
    if not reports:
        st.subheader("Recent Scans")
        st.caption("No scans yet. Upload a file above to begin.")
        return

    st.subheader("Recent Scans")
    for report_path in reports[:10]:
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        name = report_path.parent.name
        issue_count = data.get("issue_count", 0)
        col_info, col_btn = st.columns([4, 1])
        with col_info:
            icon = "✅" if issue_count == 0 else "⚠️"
            st.markdown(f"**{icon} {name}** — {issue_count} issue(s)")
            codes = data.get("issue_codes", [])
            if codes:
                st.caption(", ".join(f"`{c}`" for c in codes))
            else:
                st.caption("clean")
        with col_btn:
            if st.button("View", key=f"view_{name}"):
                # Reconstruct a ScanResult-like object from the saved report.
                from prompttrap.scanner.base import Issue, ScanResult

                issues = [
                    Issue(
                        code=i["code"],
                        severity=i["severity"],
                        message=i["message"],
                        evidence=i.get("evidence", ""),
                        location=i.get("location", {}),
                    )
                    for i in data.get("issues", [])
                ]
                result = ScanResult(
                    path=data.get("path", name),
                    file_type=data.get("file_type", ""),
                    sha256=data.get("sha256", ""),
                    size_bytes=data.get("size_bytes", 0),
                    issues=issues,
                    extracted_text=data.get("extracted_text", data.get("visible_text", "")),
                    visible_text=data.get("visible_text", ""),
                    metadata=data.get("metadata", {}),
                    processing_time_ms=data.get("processing_time_ms", 0),
                )
                st.session_state["scan_result"] = result
                st.session_state["scan_filename"] = name
                st.rerun()
        st.divider()


# ---------------------------------------------------------------------------
# Benchmark page
# ---------------------------------------------------------------------------


def render_benchmark_page() -> None:
    st.header("Benchmark Metrics")
    st.caption("Load a benchmark JSON report or generate a new one.")

    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(reports_dir.glob("*.json"), reverse=True)

    # ---- Load existing or upload ----
    col_load, col_upload = st.columns(2)

    with col_load:
        if existing:
            selected = st.selectbox(
                "Load existing report",
                options=[p.name for p in existing],
                index=0,
            )
            if st.button("Load", key="load_existing"):
                try:
                    st.session_state.pop("benchmark_data", None)
                    st.session_state["benchmark_loaded_file"] = selected
                    st.session_state["benchmark_data"] = json.loads(
                        (reports_dir / selected).read_text(encoding="utf-8")
                    )
                    st.rerun()
                except (json.JSONDecodeError, OSError) as exc:
                    st.error(f"Failed to load report: {exc}")
        else:
            st.info("No reports yet. Generate one below.")

    with col_upload:
        uploaded = st.file_uploader(
            "Or upload a benchmark JSON",
            type=["json"],
            key="benchmark_upload",
        )
        if uploaded is not None:
            try:
                st.session_state.pop("benchmark_data", None)
                st.session_state["benchmark_loaded_file"] = uploaded.name
                st.session_state["benchmark_data"] = json.loads(uploaded.getvalue())
                st.rerun()
            except json.JSONDecodeError:
                st.error("Invalid JSON file.")

    # ---- Show which report is loaded ----
    if "benchmark_data" in st.session_state:
        fname = st.session_state.get("benchmark_loaded_file", "generated")
        st.markdown(f"**Currently displaying:** `{fname}`")
        col_clear1, col_clear2 = st.columns([1, 5])
        if col_clear1.button("Clear", key="clear_benchmark"):
            st.session_state.pop("benchmark_data", None)
            st.session_state.pop("benchmark_loaded_file", None)
            st.rerun()

    # ---- Render the loaded benchmark ----
    if "benchmark_data" in st.session_state:
        _render_benchmark(st.session_state["benchmark_data"])

    # ---- Generate new benchmark ----
    st.divider()
    with st.expander("Generate a new benchmark", expanded=False):
        col_c, col_a, col_s = st.columns(3)
        clean_n = col_c.number_input("Clean files", value=150, min_value=1, step=10)
        attacked_n = col_a.number_input("Attacked files", value=150, min_value=1, step=10)
        seed = col_s.number_input("Seed", value=42, min_value=0)

        st.markdown("""
<style>
div.stButton > button[kind="primary"] {
    background: #2E8B57 !important;
    border-color: #2E8B57 !important;
}
div.stButton > button[kind="primary"]:hover {
    background: #26734a !important;
}
</style>
""", unsafe_allow_html=True)

        if st.button("Generate & Run Benchmark", type="primary", key="generate_benchmark"):
            from prompttrap.benchmark.generate_corpus import generate
            from prompttrap.benchmark.metrics import run_benchmark

            with st.spinner("Generating corpus…"):
                generate(Path("data/generated"), int(clean_n), int(attacked_n), int(seed))

            with st.spinner(f"Running benchmark (scanning {int(clean_n) + int(attacked_n)} files)…"):
                report = run_benchmark(Path("data/generated"))

            # Persist the result to disk so it can be reloaded later.
            import datetime

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = reports_dir / f"benchmark_{timestamp}.json"
            out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

            st.session_state.pop("benchmark_data", None)
            st.session_state["benchmark_loaded_file"] = out_path.name
            st.session_state["benchmark_data"] = report
            st.success(f"Benchmark saved to `{out_path.name}`.")
            st.rerun()


def _render_benchmark(data: dict[str, Any]) -> None:
    st.subheader("Overview")

    # Metric cards.
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Recall", f"{data.get('recall', 0) * 100:.1f}%")
    col2.metric("False Positive Rate", f"{data.get('false_positive_rate', 0) * 100:.1f}%")
    col3.metric("Leakage", str(data.get("sanitization_leakage", 0)))
    col4.metric("Preservation", f"{data.get('preservation', 0) * 100:.1f}%")
    col5.metric("Crash Rate", f"{data.get('crash_rate', 0) * 100:.1f}%")

    # Targets table.
    st.markdown("### Target Compliance")
    targets = [
        ("Recall", ">= 90%", data.get("recall", 0) >= 0.90),
        ("False Positive Rate", "<= 3%", data.get("false_positive_rate", 0) <= 0.03),
        ("Sanitization Leakage", "0", data.get("sanitization_leakage", 0) == 0),
        ("Preservation", ">= 95%", data.get("preservation", 0) >= 0.95),
        ("Crash Rate", "<= 1%", data.get("crash_rate", 0) <= 0.01),
    ]
    cols = st.columns(len(targets))
    for col, (metric, target, met) in zip(cols, targets):
        icon = "✅" if met else "❌"
        col.markdown(f"{icon} **{metric}**\n\nTarget: {target}")

    # Confusion matrix.
    st.markdown("### Confusion Matrix")
    cm_col1, cm_col2, cm_col3, cm_col4 = st.columns(4)
    cm_col1.metric("True Positives", data.get("true_positives", 0))
    cm_col2.metric("False Positives", data.get("false_positives", 0))
    cm_col3.metric("False Negatives", data.get("false_negatives", 0))
    cm_col4.metric("True Negatives", data.get("true_negatives", 0))

    # Counts and timing.
    col_t1, col_t2, col_t3 = st.columns(3)
    col_t1.metric("Total Cases", data.get("total", 0))
    col_t2.metric("Scored", data.get("scored", 0))
    col_t3.metric("Crashes", data.get("crashes", 0))

    avg_ms = data.get("avg_processing_ms", 0)
    st.markdown(f"**Average processing time:** {avg_ms:.1f} ms per file")

    # Per-case breakdown (rendered as markdown to avoid pyarrow segfaults).
    per_case = data.get("per_case", [])
    if per_case:
        st.markdown("### Per-Case Breakdown")
        st.caption(f"Showing {min(25, len(per_case))} of {len(per_case)} cases.")
        lines = ["| Case ID | Detected Codes | Error |", "|---|---|---|"]
        for c in per_case[:25]:
            cid = c.get("case_id", "?")
            codes = ", ".join(c.get("detected", []) or []) or "—"
            err = (c.get("error", "") or "—")[:60]
            lines.append(f"| {cid} | {codes} | {err} |")
        st.markdown("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def render_home_page() -> None:
    st.header("PromptTrap")
    st.caption("Local-first document-safety scanner — detect hidden manipulation in PDF, DOCX, HTML, and TXT files.")

    st.markdown("""
## What PromptTrap does

PromptTrap scans documents for hidden or machine-readable manipulation that could
influence AI systems — invisible text, prompt injections, encoded payloads,
zero-width characters, and more. It then produces a sanitized "safe" output with
detected payloads removed.

Everything runs locally in Docker. No files leave your machine. No paid APIs.

---

## 🔒 Security & privacy guardrails

- **Nothing leaves your machine** — all scanning happens inside the local Docker
  container. No data is uploaded to any server, API, or cloud service.
- **Temp files are deleted immediately** — uploaded files are written to a
  temporary file, scanned, and deleted in the same request. Nothing persists on
  disk unless you download a report.
- **No accounts, no tracking** — PromptTrap does not require any login and does
  not collect usage statistics or telemetry.
- **Reproducible and auditable** — all code is open and runs from a pinned
  `uv.lock` so you can verify exactly what's running.

---

## How to use this viewer

### Scan a document

1. Go to **Scan** in the sidebar.
2. Upload a PDF, DOCX, HTML, or TXT file.
3. The scanner runs automatically and shows:
   - **Summary metrics** — issue count, file type, size, scan time.
   - **Download buttons** — save a markdown summary, full JSON report, or sanitized safe text.
   - **Detected issues** — each issue is expandable with severity, code, location, and evidence.
   - **Visible vs extracted text** — side-by-side comparison of what a human sees vs what the machine reads.
   - **Sanitized safe text** — the cleaned output with payloads removed.
   - **Metadata** — document metadata fields.
4. Click **← Back to scan list** to return to the recent scans list.
5. **Recent scans** — click **View** on any past scan to reload its full result.

### View benchmark metrics

1. Go to **Benchmark** in the sidebar.
2. Either:
   - **Load an existing report** — pick a JSON file from the dropdown and click Load.
   - **Upload a benchmark JSON** — upload a report file from disk.
   - **Generate a new benchmark** — enter clean/attacked file counts and a seed, then click Generate & Run.
3. The dashboard shows:
   - **Metric cards** — recall, false positive rate, leakage, preservation, crash rate.
   - **Target compliance** — pass/fail against spec targets.
   - **Confusion matrix** — true/false positives and negatives.
   - **Per-case breakdown** — table of each scanned case and its detected codes.

---

## Supported formats and detectors

| Format | Detectors |
|--------|-----------|
| **PDF** | White text, tiny text, off-page text, metadata prompts, annotation prompts, OCR mismatch |
| **DOCX** | White text, tiny text, hidden runs (`<w:vanish/>`), comments, headers/footers, metadata prompts, alt text |
| **HTML** | `display:none`, `visibility:hidden`, `opacity:0`, white text, tiny text, off-screen text, HTML comments, meta tags, alt/title attributes, CSS class-based hiding |
| **TXT** | Zero-width Unicode, base64 payloads, prompt-like instructions |

General detectors (zero-width, base64, prompt-like) are applied to all formats.

---

## Running outside this viewer

### Scan a single file

```bash
docker compose run --rm app python -m prompttrap scan <file> --out <dir>
```

### Run the benchmark

```bash
docker compose run --rm app python -m prompttrap benchmark generate --clean 150 --attacked 150
docker compose run --rm app python -m prompttrap benchmark run --input data/generated --out reports/benchmark.json
```

### Run tests

```bash
docker compose run --rm app pytest
docker compose run --rm app ruff check .
```
""")

    st.divider()
    st.markdown("### Quick links")
    col1, col2 = st.columns(2)
    if col1.button("Go to Scan", use_container_width=True):
        st.session_state["nav_page"] = "Scan"
        st.rerun()
    if col2.button("Go to Benchmark", use_container_width=True):
        st.session_state["nav_page"] = "Benchmark"
        st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    st.sidebar.title("PromptTrap")
    st.sidebar.markdown("Document-safety scanner")

    default_page = st.session_state.pop("nav_page", "Home") if "nav_page" in st.session_state else "Home"
    page = st.sidebar.radio("Navigation", ["Home", "Scan", "Benchmark"],
                            index=["Home", "Scan", "Benchmark"].index(default_page))

    if page == "Home":
        render_home_page()
    elif page == "Scan":
        render_scan_page()
    else:
        render_benchmark_page()

    st.sidebar.divider()
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Support PromptTrap")
    st.sidebar.markdown(
        "If you find PromptTrap useful, consider supporting development:"
    )
    st.sidebar.markdown(
        '[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-%E2%98%95-yellow)]'
        '(https://www.buymeacoffee.com/promptrap)',
        unsafe_allow_html=True,
    )
    st.sidebar.caption("Built with ❤️ for safer AI document processing.")


if __name__ == "__main__":
    main()
