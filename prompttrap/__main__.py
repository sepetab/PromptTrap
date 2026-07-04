"""PromptTrap CLI entry point.

Subcommands:
    python -m prompttrap scan <file> --out <dir>
    python -m prompttrap benchmark generate --clean N --attacked M
    python -m prompttrap benchmark run --input <dir> --out <report.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from prompttrap.scanner import scan as run_scan
from prompttrap.reports.html_report import write_html_report
from prompttrap.reports.json_report import write_json_report
from prompttrap.sanitizer.safe_payload import write_safe_outputs
from prompttrap.scanner.txt import TXTScanner


def cmd_scan(args: argparse.Namespace) -> int:
    src = Path(args.file)
    if not src.is_file():
        print(f"error: file not found: {src}", file=sys.stderr)
        return 2

    result = run_scan(src)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = write_json_report(result, out_dir)
    html_path = write_html_report(result, out_dir)
    safe_paths = write_safe_outputs(result, out_dir)

    # Re-scan sanitized output to verify zero leakage.
    rescan = TXTScanner().scan(safe_paths["safe_text"])
    leakage = len(rescan.issues)

    print(f"scanned: {src}")
    print(f"sha256:  {result.sha256}")
    print(f"issues:  {len(result.issues)} ({', '.join(result.issue_codes) or 'none'})")
    print(f"leakage: {leakage}")
    print(f"output:  {out_dir}")
    print(f"  - {json_path.name}")
    print(f"  - {html_path.name}")
    print(f"  - {safe_paths['safe_text'].name}")
    print(f"  - {safe_paths['safe_payload'].name}")
    return 0


def cmd_benchmark_generate(args: argparse.Namespace) -> int:
    from prompttrap.benchmark.generate_corpus import generate

    out = Path("data/generated")
    generate(out, args.clean, args.attacked, seed=args.seed)
    print(f"Generated corpus at: {out}")
    print(f"Manifest: {out / 'manifest.jsonl'}")
    return 0


def cmd_benchmark_run(args: argparse.Namespace) -> int:
    from prompttrap.benchmark.metrics import run_benchmark

    report = run_benchmark(Path(args.input))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"benchmark report written to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prompttrap", description="Document-safety scanner.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Scan one file and write an output folder.")
    p_scan.add_argument("file", help="Path to the file to scan.")
    p_scan.add_argument("--out", default="out/scan", help="Output directory.")
    p_scan.set_defaults(func=cmd_scan)

    p_bench = sub.add_parser("benchmark", help="Benchmark tools.")
    bsub = p_bench.add_subparsers(dest="bench_command", required=True)

    p_gen = bsub.add_parser("generate", help="Generate synthetic clean/attacked corpus.")
    p_gen.add_argument("--clean", type=int, default=150)
    p_gen.add_argument("--attacked", type=int, default=150)
    p_gen.add_argument("--seed", type=int, default=42)
    p_gen.set_defaults(func=cmd_benchmark_generate)

    p_run = bsub.add_parser("run", help="Run metrics over a generated corpus.")
    p_run.add_argument("--input", required=True, help="Generated corpus directory.")
    p_run.add_argument("--out", default="reports/benchmark.json", help="Metrics report path.")
    p_run.set_defaults(func=cmd_benchmark_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
