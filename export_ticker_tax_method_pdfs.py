from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from stock_tax_report.analysis.ticker_analysis import analyze_ticker
from stock_tax_report.analysis.year_summary import _compute_aggregate_year_summaries
from stock_tax_report.domain.config import TaxConfig
from stock_tax_report.domain.fx import FxConfig
from stock_tax_report.domain.lots import BuyLot
from stock_tax_report.domain.transactions import Transaction
from stock_tax_report.io.csv_discovery import discover_csv_files
from stock_tax_report.io.csv_parser import (
    extract_transactions_from_file,
    group_by_ticker,
)
from stock_tax_report.io.fx_loader import (
    _load_cnb_daily_usd_rates,
    load_fx_rate_book,
    resolve_usd_to_czk_rate,
)
from stock_tax_report.io.parsing import (
    normalize_quantity_for_export,
    parse_date,
    parse_decimal,
)
from stock_tax_report.io.tax_config_loader import (
    _infer_template_current_year,
    load_tax_config,
    validate_tax_config,
    write_template_file,
)
from stock_tax_report.matching.standard import match_sell_transaction
from stock_tax_report.pipeline import run as run_pipeline


DEFAULT_INPUT_DIR = Path(r"C:\DATA\PROJECTS\STOCKS_raw\.csv")
DEFAULT_OUTPUT_DIR = Path(r"C:\DATA\PROJECTS\STOCKS_raw\.pdf exports tax methods")
DEFAULT_TAX_METHODS_FILE = Path(r"C:\DATA\PROJECTS\STOCKS_raw\tax_methods.toml")


def _import_reportlab_or_fail() -> None:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        print("Missing dependency: reportlab", file=sys.stderr)
        print("Install with: py -m pip install reportlab", file=sys.stderr)
        raise SystemExit(2)


def main() -> int:
    _import_reportlab_or_fail()

    parser = argparse.ArgumentParser(
        description="Export one plain PDF per ticker with tax-method matching by year."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--tax-methods-file", type=Path, default=DEFAULT_TAX_METHODS_FILE)
    parser.add_argument("--bundle-root", type=Path, default=None)
    parser.add_argument("--notes-dir", type=Path, default=None)
    parser.add_argument("--broker-exports-dir", type=Path, default=None)
    parser.add_argument(
        "--write-template",
        action="store_true",
        help="Write a tax_methods.toml template for all ticker/year combinations and exit.",
    )
    args = parser.parse_args()

    if args.write_template:
        try:
            csv_files = discover_csv_files(args.input_dir)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        all_transactions = []
        for csv_file in csv_files:
            all_transactions.extend(extract_transactions_from_file(csv_file).transactions)
        grouped = group_by_ticker(all_transactions)
        current_year = _infer_template_current_year(all_transactions)
        template_path = write_template_file(args.tax_methods_file, grouped, current_year)
        print(f"Template written: {template_path}")
        print(f"Tickers included: {len(grouped)}")
        print(f"Current year set to: {current_year}")
        return 0

    try:
        result = run_pipeline(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            tax_methods_file=args.tax_methods_file,
            generated_at=datetime.now(),
            bundle_root=args.bundle_root,
            notes_dir=args.notes_dir,
            broker_exports_dir=args.broker_exports_dir,
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


if __name__ == "__main__":
    raise SystemExit(main())
