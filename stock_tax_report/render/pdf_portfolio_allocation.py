from __future__ import annotations

from datetime import datetime
from pathlib import Path

from stock_tax_report.domain.portfolio import PortfolioAllocationResult
from stock_tax_report.render.formatting import _fmt_decimal
from stock_tax_report.render.pdf_styles import create_all_tickers_pdf_styles


def _build_pie_chart(allocation: PortfolioAllocationResult):
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors

    drawing = Drawing(520, 270)
    pie = Pie()
    pie.x = 150
    pie.y = 25
    pie.width = 210
    pie.height = 210
    pie.sideLabels = 1
    pie.simpleLabels = 0
    pie.data = [float(item.value_usd) for item in allocation.items]
    pie.labels = [
        f"{item.ticker} {_fmt_decimal(item.allocation_percent, 1)}%"
        for item in allocation.items
    ]

    palette = [
        colors.HexColor("#2563eb"),
        colors.HexColor("#16a34a"),
        colors.HexColor("#dc2626"),
        colors.HexColor("#f59e0b"),
        colors.HexColor("#7c3aed"),
        colors.HexColor("#0891b2"),
        colors.HexColor("#db2777"),
        colors.HexColor("#65a30d"),
        colors.HexColor("#4b5563"),
        colors.HexColor("#ea580c"),
        colors.HexColor("#0f766e"),
        colors.HexColor("#9333ea"),
    ]
    for index, _item in enumerate(allocation.items):
        pie.slices[index].fillColor = palette[index % len(palette)]

    drawing.add(pie)
    return drawing


def _build_allocation_table(allocation: PortfolioAllocationResult):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    rows = [["Ticker", "Open Qty", "Price USD", "Value USD", "Allocation"]]
    for item in allocation.items:
        rows.append(
            [
                item.ticker,
                _fmt_decimal(item.quantity, 5),
                _fmt_decimal(item.price_usd),
                _fmt_decimal(item.value_usd),
                f"{_fmt_decimal(item.allocation_percent, 2)}%",
            ]
        )
    rows.append(["Total", "", "", _fmt_decimal(allocation.total_value_usd), "100.00%"])

    table = Table(rows, repeatRows=1, colWidths=[80, 100, 100, 120, 100], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.white),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def build_portfolio_allocation_pdf(
    allocation: PortfolioAllocationResult,
    output_dir: Path,
    generated_at: datetime,
) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    output_path = output_dir / "_portfolio_allocation.pdf"
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=24,
        rightMargin=24,
        topMargin=22,
        bottomMargin=22,
        title="Portfolio allocation",
    )

    styles = create_all_tickers_pdf_styles()
    title_style = styles["title_style"]
    note_style = styles["note_style"]

    snapshot = allocation.price_snapshot
    source = snapshot.provider if snapshot is not None else "unknown"
    fetched_at = snapshot.fetched_at if snapshot is not None else generated_at

    story = [
        Paragraph(
            "Portfolio Allocation | "
            f"Source: {source} | "
            f"Prices fetched: {fetched_at.strftime('%Y-%m-%d %H:%M:%S')} | "
            f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            title_style,
        ),
        Spacer(1, 8),
    ]

    if allocation.items:
        story.append(_build_pie_chart(allocation))
        story.append(Spacer(1, 10))
        story.append(_build_allocation_table(allocation))
    else:
        story.append(Paragraph("No open positions with available market prices.", note_style))

    if allocation.warnings:
        story.append(Spacer(1, 8))
        story.append(
            Paragraph(
                "Some symbols were excluded because current market prices were unavailable. "
                "See _export_warnings.txt and _market_prices_snapshot.json for details.",
                note_style,
            )
        )

    doc.build(story)
    return output_path
