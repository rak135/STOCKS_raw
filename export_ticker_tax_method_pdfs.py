from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import List

from stock_tax_report.analysis.ticker_analysis import analyze_ticker
from stock_tax_report.analysis.year_summary import _compute_aggregate_year_summaries
from stock_tax_report.domain.analysis import TickerAnalysis
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
from stock_tax_report.render.cleanup import _clear_previous_exports
from stock_tax_report.render.pdf_all_tickers import build_all_tickers_year_summary_pdf
from stock_tax_report.render.pdf_ticker import build_pdf_for_ticker
from stock_tax_report.render.summary_csv import write_summary
from stock_tax_report.render.warnings_txt import write_warnings


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
    parser.add_argument(
        "--write-template",
        action="store_true",
        help="Write a tax_methods.toml template for all ticker/year combinations and exit.",
    )
    args = parser.parse_args()

    try:
        csv_files = discover_csv_files(args.input_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    all_transactions: List[Transaction] = []
    all_warnings: List[str] = []
    all_mapping_notes: List[str] = []

    for csv_file in csv_files:
        result = extract_transactions_from_file(csv_file)
        all_transactions.extend(result.transactions)
        all_warnings.extend(result.warnings)
        all_mapping_notes.extend(result.mapping_notes)

    grouped = group_by_ticker(all_transactions)

    if args.write_template:
        current_year = _infer_template_current_year(all_transactions)
        template_path = write_template_file(args.tax_methods_file, grouped, current_year)
        print(f"Template written: {template_path}")
        print(f"Tickers included: {len(grouped)}")
        print(f"Current year set to: {current_year}")
        return 0

    try:
        config = load_tax_config(args.tax_methods_file)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        fx_rate_book = load_fx_rate_book(config.fx_config)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    validation_errors = validate_tax_config(grouped, config)
    if validation_errors:
        print("Tax methods validation failed:", file=sys.stderr)
        for error in validation_errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    analyses: List[TickerAnalysis] = []
    try:
        for ticker, transactions in grouped.items():
            analyses.append(analyze_ticker(ticker, transactions, config))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _clear_previous_exports(args.output_dir)

    generated_at = datetime.now()
    created_pdfs: List[Path] = []
    for analysis in analyses:
        created_pdfs.append(build_pdf_for_ticker(analysis, args.output_dir, generated_at, config.current_year, fx_rate_book))
    all_tickers_summary_pdf = build_all_tickers_year_summary_pdf(
        analyses,
        args.output_dir,
        generated_at,
        config.current_year,
        fx_rate_book,
    )

    summary_path = write_summary(args.output_dir, analyses, fx_rate_book)
    warnings_path = write_warnings(args.output_dir, all_warnings, all_mapping_notes, analyses, generated_at)

    ignored_current_year_sell_count = sum(len(item.ignored_current_year_sells) for item in analyses)

    print(f"CSV files read: {len(csv_files)}")
    print(f"Valid BUY/SELL transactions parsed: {len(all_transactions)}")
    print(f"Ticker PDFs created: {len(created_pdfs)}")
    print(f"Ignored current-year SELL transactions: {ignored_current_year_sell_count}")
    print(f"All-tickers year summary PDF: {all_tickers_summary_pdf}")
    for pdf_path in created_pdfs:
        print(f"PDF: {pdf_path}")
    print(f"Summary: {summary_path}")
    print(f"Warnings: {warnings_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
