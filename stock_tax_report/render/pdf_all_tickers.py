from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from stock_tax_report.analysis.year_summary import _compute_aggregate_year_summaries
from stock_tax_report.domain.analysis import TickerAnalysis
from stock_tax_report.domain.fx import FxRateBook
from stock_tax_report.render.formatting import _fmt_usd_czk_pair, _year_fx_label
from stock_tax_report.render.pdf_styles import create_all_tickers_pdf_styles


def build_all_tickers_year_summary_pdf(
    analyses: List[TickerAnalysis],
    output_dir: Path,
    generated_at: datetime,
    current_year: int,
    fx_rate_book: FxRateBook,
) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output_path = output_dir / "_all_tickers_year_summary.pdf"
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18,
        rightMargin=18,
        topMargin=20,
        bottomMargin=20,
        title="All tickers year summary",
    )

    styles = create_all_tickers_pdf_styles()
    title_style = styles["title_style"]
    note_style = styles["note_style"]

    aggregated = _compute_aggregate_year_summaries(analyses, current_year, fx_rate_book)
    rows = [[
        "Year",
        "FX",
        "Income USD/CZK",
        "Profit/Loss USD/CZK",
        "3 years rule PASS USD/CZK",
        "3 years rule FAIL USD/CZK",
    ]]

    for year in sorted(aggregated, reverse=True):
        summary = aggregated[year]
        rows.append([
            str(year),
            _year_fx_label(year, current_year, fx_rate_book),
            _fmt_usd_czk_pair(summary.total_income, summary.total_income_czk),
            _fmt_usd_czk_pair(summary.total_pl, summary.total_pl_czk),
            _fmt_usd_czk_pair(summary.over_three_year_pl, summary.over_three_year_pl_czk),
            _fmt_usd_czk_pair(summary.taxable_pl, summary.taxable_pl_czk),
        ])

    table = Table(rows, repeatRows=1, colWidths=[46, 48, 102, 102, 112, 112], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.white),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )

    story = [
        Paragraph(
            f"All Tickers Year Summary | FX mode: {fx_rate_book.mode} | Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            title_style,
        ),
        Spacer(1, 8),
        table,
    ]
    if current_year in aggregated:
        story.extend(
            [
                Spacer(1, 6),
                Paragraph(
                    "Current year follows the same export rule as ticker PDFs. Tax columns remain blank when tax matching is not applied.",
                    note_style,
                ),
            ]
        )

    doc.build(story)
    return output_path
