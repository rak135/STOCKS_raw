from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from stock_tax_report.analysis.year_summary import _compute_aggregate_year_summaries
from stock_tax_report.domain.analysis import TickerAnalysis, YearSummary
from stock_tax_report.domain.fx import FxRateBook
from stock_tax_report.render.formatting import _fmt_usd_czk_pair, _year_fx_label
from stock_tax_report.render.pdf_styles import create_all_tickers_pdf_styles


def _build_metric_table(label: str, income, income_czk, costs, costs_czk, profit, profit_czk):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    rows = [
        [label, "Income USD/CZK", "Costs USD/CZK", "Profit USD/CZK"],
        ["", _fmt_usd_czk_pair(income, income_czk), _fmt_usd_czk_pair(costs, costs_czk), _fmt_usd_czk_pair(profit, profit_czk)],
    ]
    table = Table(rows, repeatRows=1, colWidths=[58, 148, 148, 148], hAlign="LEFT")
    background = colors.HexColor("#eeeeee") if label == "3y FAIL" else colors.white
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def _build_year_summary_tables(summary: YearSummary):
    return [
        _build_metric_table(
            "Total",
            summary.total_income,
            summary.total_income_czk,
            summary.total_costs,
            summary.total_costs_czk,
            summary.total_pl,
            summary.total_pl_czk,
        ),
        _build_metric_table(
            "3y PASS",
            summary.pass_income,
            summary.pass_income_czk,
            summary.pass_costs,
            summary.pass_costs_czk,
            summary.over_three_year_pl,
            summary.over_three_year_pl_czk,
        ),
        _build_metric_table(
            "3y FAIL",
            summary.fail_income,
            summary.fail_income_czk,
            summary.fail_costs,
            summary.fail_costs_czk,
            summary.taxable_pl,
            summary.taxable_pl_czk,
        ),
    ]


def build_all_tickers_year_summary_pdf(
    analyses: List[TickerAnalysis],
    output_dir: Path,
    generated_at: datetime,
    current_year: int,
    fx_rate_book: FxRateBook,
) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import CondPageBreak, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

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
    year_style = styles["year_style"]
    note_style = styles["note_style"]

    aggregated = _compute_aggregate_year_summaries(analyses, current_year, fx_rate_book)

    story = [
        Paragraph(
            f"All Tickers Year Summary | FX mode: per-year | Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            title_style,
        ),
        Spacer(1, 8),
    ]

    for index, year in enumerate(sorted(aggregated, reverse=True)):
        if index > 0:
            story.append(Spacer(1, 8))
        summary_tables = _build_year_summary_tables(aggregated[year])
        story.append(CondPageBreak(130))
        story.append(
            KeepTogether(
                [
                    Paragraph(f"Year: {year} | {_year_fx_label(year, current_year, fx_rate_book)}", year_style),
                    Spacer(1, 4),
                    summary_tables[0],
                    Spacer(1, 3),
                    summary_tables[1],
                    Spacer(1, 3),
                    summary_tables[2],
                ]
            )
        )
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
