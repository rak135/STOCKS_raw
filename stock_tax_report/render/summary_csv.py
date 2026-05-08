from __future__ import annotations

import csv
from pathlib import Path
from typing import List

from stock_tax_report.analysis.year_summary import _compute_income_costs_by_time_test
from stock_tax_report.domain.analysis import TickerAnalysis
from stock_tax_report.domain.fx import FxRateBook
from stock_tax_report.render.formatting import _fmt_decimal, _safe_pdf_name


def write_summary(output_dir: Path, analyses: List[TickerAnalysis], fx_rate_book: FxRateBook) -> Path:
    summary_path = output_dir / "_export_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ticker",
                "pdf_file",
                "fx_modes",
                "year_count",
                "sell_count",
                "ignored_current_year_sell_count",
                "open_qty",
                "total_income_usd",
                "total_income_czk",
                "total_costs_usd",
                "total_costs_czk",
                "total_profit_usd",
                "total_profit_czk",
                "income_3y_pass_usd",
                "income_3y_pass_czk",
                "costs_3y_pass_usd",
                "costs_3y_pass_czk",
                "profit_3y_pass_usd",
                "profit_3y_pass_czk",
                "income_3y_fail_usd",
                "income_3y_fail_czk",
                "costs_3y_fail_usd",
                "costs_3y_fail_czk",
                "profit_3y_fail_usd",
                "profit_3y_fail_czk",
                "source_files",
            ]
        )

        for analysis in analyses:
            sell_count = sum(len(items) for items in analysis.sell_matches_by_year.values())
            sell_matches = [
                sell_match
                for year_matches in analysis.sell_matches_by_year.values()
                for sell_match in year_matches
            ]
            total, passed, failed = _compute_income_costs_by_time_test(
                sell_matches, fx_rate_book
            )
            fx_modes = ";".join(
                f"{year}={fx_rate_book.mode_for(year) or '?'}" for year in sorted(analysis.years)
            )
            writer.writerow(
                [
                    analysis.ticker,
                    f"{_safe_pdf_name(analysis.ticker)}.pdf",
                    fx_modes,
                    len(analysis.years),
                    sell_count,
                    len(analysis.ignored_current_year_sells),
                    _fmt_decimal(analysis.open_quantity),
                    _fmt_decimal(total.income),
                    _fmt_decimal(total.income_czk),
                    _fmt_decimal(total.costs),
                    _fmt_decimal(total.costs_czk),
                    _fmt_decimal(total.profit),
                    _fmt_decimal(total.profit_czk),
                    _fmt_decimal(passed.income),
                    _fmt_decimal(passed.income_czk),
                    _fmt_decimal(passed.costs),
                    _fmt_decimal(passed.costs_czk),
                    _fmt_decimal(passed.profit),
                    _fmt_decimal(passed.profit_czk),
                    _fmt_decimal(failed.income),
                    _fmt_decimal(failed.income_czk),
                    _fmt_decimal(failed.costs),
                    _fmt_decimal(failed.costs_czk),
                    _fmt_decimal(failed.profit),
                    _fmt_decimal(failed.profit_czk),
                    ";".join(analysis.source_files),
                ]
            )

    return summary_path
