from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from stock_tax_report.io.csv_discovery import discover_csv_files
from stock_tax_report.io.csv_parser import (
    extract_transactions_from_file,
    group_by_ticker,
)
from stock_tax_report.io.paths_loader import REPO_ROOT, ReportPaths, load_report_paths
from stock_tax_report.io.tax_config_loader import (
    _infer_template_current_year,
    write_template_file,
)
from stock_tax_report.pipeline import run as run_pipeline


DEFAULT_PATHS_FILE = REPO_ROOT / "report_paths.toml"


def _import_reportlab_or_fail() -> None:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        print("Missing dependency: reportlab", file=sys.stderr)
        print("Install with: py -m pip install reportlab", file=sys.stderr)
        raise SystemExit(2)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_tax_report",
        description="Run the tax report pipeline and assemble a tax_<year>/ evidence bundle.",
    )
    parser.add_argument("--paths-config", type=Path, default=None,
                        help=f"Path to report_paths.toml. Defaults to {DEFAULT_PATHS_FILE} if it exists.")
    parser.add_argument("--input-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--tax-methods-file", type=Path, default=None)
    parser.add_argument("--bundle-root", type=Path, default=None,
                        help="Bundle output root. Pass empty string to skip bundle assembly.")
    parser.add_argument("--no-bundle", action="store_true",
                        help="Skip bundle assembly even if bundle_root is configured.")
    parser.add_argument("--notes-dir", type=Path, default=None)
    parser.add_argument("--broker-exports-dir", type=Path, default=None)
    parser.add_argument(
        "--write-template",
        action="store_true",
        help="Write a tax_methods.toml template for all ticker/year combinations and exit.",
    )
    return parser


def _resolve_paths(args: argparse.Namespace) -> ReportPaths:
    paths_file = args.paths_config
    if paths_file is None and DEFAULT_PATHS_FILE.exists():
        paths_file = DEFAULT_PATHS_FILE

    paths = load_report_paths(paths_file)

    if args.input_dir is not None:
        paths.normalized_csv_dir = args.input_dir
    if args.output_dir is not None:
        paths.output_dir = args.output_dir
    if args.tax_methods_file is not None:
        paths.tax_methods_file = args.tax_methods_file
    if args.bundle_root is not None:
        paths.bundle_root = args.bundle_root
    if args.notes_dir is not None:
        paths.notes_dir = args.notes_dir
    if args.broker_exports_dir is not None:
        paths.broker_exports_dir = args.broker_exports_dir

    return paths


def _run_write_template(paths: ReportPaths) -> int:
    try:
        csv_files = discover_csv_files(paths.normalized_csv_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    transactions = []
    for csv_file in csv_files:
        transactions.extend(extract_transactions_from_file(csv_file).transactions)
    grouped = group_by_ticker(transactions)
    current_year = _infer_template_current_year(transactions)
    template_path = write_template_file(paths.tax_methods_file, grouped, current_year)
    print(f"Template written: {template_path}")
    print(f"Tickers included: {len(grouped)}")
    print(f"Current year set to: {current_year}")
    return 0


def _existing_optional(path: Optional[Path]) -> Optional[Path]:
    if path is None:
        return None
    return path if path.exists() else None


def main(argv: Optional[Sequence[str]] = None) -> int:
    _import_reportlab_or_fail()

    parser = _build_parser()
    args = parser.parse_args(argv)
    paths = _resolve_paths(args)

    if args.write_template:
        return _run_write_template(paths)

    bundle_root: Optional[Path] = None if args.no_bundle else paths.bundle_root

    try:
        result = run_pipeline(
            input_dir=paths.normalized_csv_dir,
            output_dir=paths.output_dir,
            tax_methods_file=paths.tax_methods_file,
            generated_at=datetime.now(),
            bundle_root=bundle_root,
            notes_dir=_existing_optional(paths.notes_dir),
            broker_exports_dir=_existing_optional(paths.broker_exports_dir),
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"CSV files read: {result.csv_files_read}")
    print(f"Valid BUY/SELL transactions parsed: {result.transactions_parsed}")
    print(f"Ticker PDFs created: {result.pdfs_created}")
    print(f"Ignored current-year SELL transactions: {result.ignored_current_year_sells}")
    print(f"All-tickers year summary PDF: {result.all_tickers_pdf_path}")
    for pdf_path in result.pdf_paths:
        print(f"PDF: {pdf_path}")
    print(f"Summary: {result.summary_csv_path}")
    print(f"Warnings: {result.warnings_txt_path}")
    if result.bundle_dir is not None:
        print(f"Bundle: {result.bundle_dir}")

    return 0
