from __future__ import annotations

import csv
from pathlib import Path
from typing import List

from stock_tax_report.analysis.year_summary import _compute_fail_income_costs
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
                "income_3y_fail_usd",
                "income_3y_fail_czk",
                "costs_3y_fail_usd",
                "costs_3y_fail_czk",
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
            fail_income, fail_income_czk, fail_costs, fail_costs_czk = _compute_fail_income_costs(
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
                    _fmt_decimal(fail_income),
                    _fmt_decimal(fail_income_czk),
                    _fmt_decimal(fail_costs),
                    _fmt_decimal(fail_costs_czk),
                    ";".join(analysis.source_files),
                ]
            )

    return summary_path
