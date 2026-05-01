from __future__ import annotations


OPEN_POSITIONS_COL_WIDTHS = [120, 80]
YEAR_HISTORY_COL_WIDTHS = [102, 38, 46, 40, 86, 70, 82, 84]


def create_ticker_pdf_styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    styles = getSampleStyleSheet()
    title_style = styles["Heading4"]
    title_style.textColor = colors.black
    year_style = ParagraphStyle(
        "YearHeading",
        parent=styles["Heading5"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=colors.black,
        spaceAfter=0,
    )
    note_style = ParagraphStyle(
        "NoteStyle",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=colors.black,
        spaceAfter=0,
    )
    header_cell_style = ParagraphStyle(
        "HeaderCell",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=8,
        textColor=colors.black,
    )
    source_cell_style = ParagraphStyle(
        "SourceCell",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=6.5,
        leading=7.5,
        textColor=colors.black,
    )
    buy_block_cell_style = ParagraphStyle(
        "BuyBlockCell",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=6.4,
        leading=7.4,
        textColor=colors.black,
    )
    sell_block_cell_style = ParagraphStyle(
        "SellBlockCell",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=6.4,
        leading=7.4,
        textColor=colors.black,
    )
    lot_cell_style = ParagraphStyle(
        "LotCell",
        parent=styles["BodyText"],
        fontName="Helvetica-Oblique",
        fontSize=6.2,
        leading=7.2,
        textColor=colors.black,
    )
    return {
        "title_style": title_style,
        "year_style": year_style,
        "note_style": note_style,
        "header_cell_style": header_cell_style,
        "source_cell_style": source_cell_style,
        "buy_block_cell_style": buy_block_cell_style,
        "sell_block_cell_style": sell_block_cell_style,
        "lot_cell_style": lot_cell_style,
    }


def create_all_tickers_pdf_styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    styles = getSampleStyleSheet()
    title_style = styles["Heading4"]
    title_style.textColor = colors.black
    note_style = ParagraphStyle(
        "SummaryNote",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=colors.black,
    )
    return {
        "title_style": title_style,
        "note_style": note_style,
    }
