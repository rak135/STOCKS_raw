from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from stock_tax_report.analysis.trade_value import (
    _buy_transaction_key,
    _compute_trade_value,
    _compute_trade_value_czk,
    _sell_match_key,
    _transaction_key,
)
from stock_tax_report.analysis.year_summary import _compute_year_summary
from stock_tax_report.domain.analysis import TickerAnalysis, YearSummary
from stock_tax_report.domain.fx import FxRateBook
from stock_tax_report.io.fx_loader import resolve_usd_to_czk_rate
from stock_tax_report.render.formatting import (
    METHOD_LABELS,
    _fmt_decimal,
    _fmt_usd_czk_pair,
    _format_match_status,
    _safe_pdf_name,
    _source_ref,
    _year_fx_label,
)
from stock_tax_report.render.pdf_styles import (
    OPEN_POSITIONS_COL_WIDTHS,
    YEAR_HISTORY_COL_WIDTHS,
    create_ticker_pdf_styles,
)


def _build_year_summary_table(summary: YearSummary):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    rows = [[
        "Income USD/CZK",
        "Profit/Loss USD/CZK",
        "3 years rule PASS USD/CZK",
        "3 years rule FAIL USD/CZK",
    ]]
    rows.append([
        _fmt_usd_czk_pair(summary.total_income, summary.total_income_czk),
        _fmt_usd_czk_pair(summary.total_pl, summary.total_pl_czk),
        _fmt_usd_czk_pair(summary.over_three_year_pl, summary.over_three_year_pl_czk),
        _fmt_usd_czk_pair(summary.taxable_pl, summary.taxable_pl_czk),
    ])

    table = Table(rows, repeatRows=1, colWidths=[125, 125, 125, 125], hAlign="LEFT")
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
    return table


def _build_year_history_table(
    analysis: TickerAnalysis,
    year: int,
    current_year: int,
    fx_rate_book: FxRateBook,
    styles,
):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    header_style = styles["header_cell_style"]
    body_style = styles["source_cell_style"]
    lot_style = styles["lot_cell_style"]
    buy_block_style = styles["buy_block_cell_style"]
    sell_block_style = styles["sell_block_cell_style"]

    sell_matches_by_key = {
        _sell_match_key(sell_match): sell_match
        for sell_match in analysis.sell_matches_by_year.get(year, [])
    }
    year_transactions = [tx for tx in analysis.transactions if tx.date.year == year]
    detail_row_indexes: List[int] = []
    sell_main_row_indexes: List[int] = []

    rows = [[
        Paragraph("Date / Block", header_style),
        "Qty",
        Paragraph("Unit Price", header_style),
        Paragraph("FX", header_style),
        Paragraph("Value USD/CZK", header_style),
        Paragraph("Taxable P/L", header_style),
        Paragraph("Match Detail", header_style),
        Paragraph("Source / Row", header_style),
    ]]

    for tx in reversed(year_transactions):
        sell_match = sell_matches_by_key.get(_transaction_key(tx))
        taxable_pl = sell_match.total_taxable_pl if sell_match is not None else None
        buy_usages = analysis.buy_usages_by_key.get(_buy_transaction_key(tx), [])
        is_used_buy = tx.action == "BUY" and bool(buy_usages)
        note_prefix = "* " if is_used_buy else ""
        block_label = f"{note_prefix}{tx.date.isoformat()} {tx.action}"
        block_style = sell_block_style if tx.action == "SELL" else buy_block_style
        tx_value_usd = _compute_trade_value(tx.quantity, tx.price)
        tx_fx_rate = None
        tx_value_czk = None

        if year < current_year and tx.price is not None:
            tx_fx_rate = resolve_usd_to_czk_rate(fx_rate_book, tx.date)
            tx_value_czk = _compute_trade_value_czk(tx.quantity, tx.price, tx.date, fx_rate_book)

        if year == current_year and tx.action == "SELL":
            block_label = f"{tx.date.isoformat()} SELL (ignored)"
            taxable_pl = None

        rows.append([
            Paragraph(block_label, block_style),
            _fmt_decimal(tx.quantity),
            _fmt_decimal(tx.price),
            _fmt_decimal(tx_fx_rate),
            _fmt_usd_czk_pair(tx_value_usd, tx_value_czk),
            _fmt_decimal(taxable_pl),
            "",
            Paragraph(_source_ref(tx.source_file, tx.original_row_number), body_style),
        ])
        if tx.action == "SELL":
            sell_main_row_indexes.append(len(rows) - 1)

        if sell_match is not None:
            for lot_number, match in enumerate(sell_match.matches, start=1):
                match_fx_rate = resolve_usd_to_czk_rate(fx_rate_book, match.buy_date)
                rows.append([
                    Paragraph(f"* Lot #{lot_number} | Bought {match.buy_date.isoformat()}", lot_style),
                    _fmt_decimal(match.matched_qty),
                    _fmt_decimal(match.buy_price),
                    _fmt_decimal(match_fx_rate),
                    _fmt_usd_czk_pair(
                        _compute_trade_value(match.matched_qty, match.buy_price),
                        _compute_trade_value_czk(match.matched_qty, match.buy_price, match.buy_date, fx_rate_book),
                    ),
                    _fmt_decimal(match.total_pl),
                    Paragraph(_format_match_status(match.time_test_passed, match.holding_period_days), lot_style),
                    Paragraph(_source_ref(match.buy_source_file, match.buy_row_number), lot_style),
                ])
                detail_row_indexes.append(len(rows) - 1)
        elif buy_usages:
            for usage_number, usage in enumerate(buy_usages, start=1):
                usage_fx_rate = resolve_usd_to_czk_rate(fx_rate_book, usage.sell_date)
                rows.append([
                    Paragraph(f"* Split #{usage_number} | Sold {usage.sell_date.isoformat()}", lot_style),
                    _fmt_decimal(usage.matched_qty),
                    _fmt_decimal(usage.sell_price),
                    _fmt_decimal(usage_fx_rate),
                    _fmt_usd_czk_pair(
                        _compute_trade_value(usage.matched_qty, usage.sell_price),
                        _compute_trade_value_czk(usage.matched_qty, usage.sell_price, usage.sell_date, fx_rate_book),
                    ),
                    _fmt_decimal(usage.total_pl),
                    Paragraph(_format_match_status(usage.time_test_passed, usage.holding_period_days), lot_style),
                    Paragraph(_source_ref(usage.sell_source_file, usage.sell_row_number), lot_style),
                ])
                detail_row_indexes.append(len(rows) - 1)
        elif year == current_year and tx.action == "SELL":
            rows.append([
                Paragraph("* Current year | No tax matching", lot_style),
                "",
                "",
                "",
                Paragraph("Not included", lot_style),
                Paragraph("Not included", lot_style),
                "",
                "",
            ])
            detail_row_indexes.append(len(rows) - 1)

    style_commands = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.white),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 6.3),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]

    for row_index in detail_row_indexes:
        style_commands.extend(
            [
                ("FONTNAME", (0, row_index), (-1, row_index), "Helvetica-Oblique"),
                ("LEFTPADDING", (0, row_index), (0, row_index), 14),
                ("BOTTOMPADDING", (0, row_index), (-1, row_index), 2),
                ("TOPPADDING", (0, row_index), (-1, row_index), 2),
            ]
        )

    for row_index in sell_main_row_indexes:
        style_commands.extend(
            [
                ("FONTNAME", (0, row_index), (-1, row_index), "Helvetica-Bold"),
                ("FONTSIZE", (0, row_index), (-1, row_index), 6.5),
            ]
        )

    table = Table(rows, repeatRows=1, colWidths=YEAR_HISTORY_COL_WIDTHS)
    table.setStyle(TableStyle(style_commands))
    return table


def build_pdf_for_ticker(
    analysis: TickerAnalysis,
    output_dir: Path,
    generated_at: datetime,
    current_year: int,
    fx_rate_book: FxRateBook,
) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import CondPageBreak, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output_path = output_dir / f"{_safe_pdf_name(analysis.ticker)}.pdf"
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18,
        rightMargin=18,
        topMargin=20,
        bottomMargin=20,
        title=f"{analysis.ticker} tax trade history",
    )

    styles = create_ticker_pdf_styles()
    title_style = styles["title_style"]
    year_style = styles["year_style"]
    note_style = styles["note_style"]

    story = []
    story.append(
        Paragraph(
            f"Ticker: {analysis.ticker} | Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            title_style,
        )
    )
    story.append(Spacer(1, 8))

    story.append(Paragraph("Open Positions", year_style))
    story.append(Spacer(1, 4))
    open_rows = [["Ticker", "Open Qty"]]
    open_rows.append([analysis.ticker, _fmt_decimal(analysis.open_quantity)])

    open_table = Table(open_rows, repeatRows=1, colWidths=OPEN_POSITIONS_COL_WIDTHS, hAlign="LEFT")
    open_table.setStyle(
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
    story.append(open_table)
    story.append(Spacer(1, 10))

    for index, year in enumerate(analysis.years):
        if index > 0:
            story.append(Spacer(1, 10))

        heading = f"Year: {year}"
        if year < current_year:
            heading = f"{heading} | Method: {METHOD_LABELS[analysis.year_methods[year]]} | {_year_fx_label(year, current_year, fx_rate_book)}"
        else:
            heading = f"{heading} | {_year_fx_label(year, current_year, fx_rate_book)}"
        year_summary_table = _build_year_summary_table(_compute_year_summary(analysis, year, current_year, fx_rate_book))
        story.append(CondPageBreak(170))
        story.append(
            KeepTogether(
                [
                    Paragraph(heading, year_style),
                    Spacer(1, 4),
                    year_summary_table,
                ]
            )
        )
        story.append(Spacer(1, 6))

        story.append(_build_year_history_table(analysis, year, current_year, fx_rate_book, styles))
        story.append(Spacer(1, 8))

        if year == current_year and analysis.ignored_current_year_sells:
            story.append(
                Paragraph(
                    "Current-year SELL rows are shown in history, but they are not included in tax matching.",
                    note_style,
                )
            )
            story.append(Spacer(1, 2))

    doc.build(story)
    return output_path
