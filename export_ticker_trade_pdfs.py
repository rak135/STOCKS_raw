from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_INPUT_DIR = Path(r"C:\DATA\PROJECTS\STOCKS_raw\.csv")
DEFAULT_OUTPUT_DIR = Path(r"C:\DATA\PROJECTS\STOCKS_raw\.pdf exports")


def _import_reportlab_or_fail() -> None:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        print("Missing dependency: reportlab", file=sys.stderr)
        print("Install with: py -m pip install reportlab", file=sys.stderr)
        raise SystemExit(2)


@dataclass
class Transaction:
    source_file: str
    broker_source: str
    ticker: str
    action: str
    date: date
    quantity: Decimal
    price: Optional[Decimal]
    currency: Optional[str]
    fee: Optional[Decimal]
    gross_amount: Optional[Decimal]
    original_row_number: int


@dataclass
class FileExtractionResult:
    transactions: List[Transaction]
    warnings: List[str]
    mapping_notes: List[str]


@dataclass
class OpenPositionLot:
    source_file: str
    ticker: str
    buy_date: date
    quantity: Decimal
    price: Optional[Decimal]
    currency: Optional[str]
    fee: Optional[Decimal]
    original_row_number: int


def discover_csv_files(input_dir: Path) -> List[Path]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    return sorted(p for p in input_dir.glob("*.csv") if p.is_file())


def detect_dialect(sample_text: str) -> csv.Dialect:
    sniff = csv.Sniffer()
    for delimiters in [",;\t", ",;", "\t", ","]:
        try:
            return sniff.sniff(sample_text, delimiters=delimiters)
        except csv.Error:
            continue

    class Fallback(csv.Dialect):
        delimiter = ","
        quotechar = '"'
        doublequote = True
        skipinitialspace = True
        lineterminator = "\n"
        quoting = csv.QUOTE_MINIMAL

    return Fallback()


def _normalize_header_name(name: str) -> str:
    return re.sub(r"\s+", "", name.strip().lower())


def _first_matching_header(fieldnames: Iterable[str], aliases: Iterable[str]) -> Optional[str]:
    normalized_to_field: Dict[str, str] = {}
    for field in fieldnames:
        key = _normalize_header_name(field)
        if key not in normalized_to_field:
            normalized_to_field[key] = field

    for alias in aliases:
        key = _normalize_header_name(alias)
        if key in normalized_to_field:
            return normalized_to_field[key]
    return None


def parse_decimal(value: str) -> Optional[Decimal]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    text = text.replace("\u00a0", "").replace(" ", "")
    text = re.sub(r"[^0-9,\.\-+eE]", "", text)
    if not text:
        return None

    comma_pos = text.rfind(",")
    dot_pos = text.rfind(".")

    if comma_pos >= 0 and dot_pos >= 0:
        if comma_pos > dot_pos:
            text = text.replace(".", "")
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif comma_pos >= 0:
        text = text.replace(".", "")
        text = text.replace(",", ".")

    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_date(value: str) -> Optional[date]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y%m%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    digits_only = re.sub(r"\D", "", text)
    if len(digits_only) == 8:
        for fmt in ["%Y%m%d", "%d%m%Y", "%m%d%Y"]:
            try:
                return datetime.strptime(digits_only, fmt).date()
            except ValueError:
                continue

    return None


def normalize_action(value: str) -> Optional[str]:
    if value is None:
        return None
    text = value.strip().upper()
    if not text:
        return None

    alias_map = {
        "BUY": "BUY",
        "B": "BUY",
        "PURCHASE": "BUY",
        "BOUGHT": "BUY",
        "KUPNO": "BUY",
        "SELL": "SELL",
        "S": "SELL",
        "SOLD": "SELL",
        "SPRZEDAZ": "SELL",
        "SPRZEDAŻ": "SELL",
    }
    return alias_map.get(text)


def normalize_ticker(value: str) -> str:
    if value is None:
        return ""
    return value.strip().upper()


def normalize_quantity_for_export(action: str, quantity: Decimal) -> Decimal:
    if action != "SELL":
        return quantity

    fractional_part = quantity % 1
    if fractional_part == Decimal("0.99999"):
        return quantity.to_integral_value(rounding=ROUND_CEILING)

    return quantity


def _infer_broker_source(file_path: Path) -> str:
    stem = file_path.stem.strip()
    if "_" in stem:
        return stem.split("_", 1)[0]
    return stem


def extract_transactions_from_file(file_path: Path) -> FileExtractionResult:
    warnings: List[str] = []
    mapping_notes: List[str] = []
    transactions: List[Transaction] = []

    try:
        raw_text = file_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        warnings.append(f"{file_path.name}: file could not be parsed ({exc})")
        return FileExtractionResult([], warnings, mapping_notes)

    sample = raw_text[:10000] if raw_text else ""
    dialect = detect_dialect(sample)

    reader = csv.DictReader(raw_text.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        warnings.append(f"{file_path.name}: file could not be parsed (missing headers)")
        return FileExtractionResult([], warnings, mapping_notes)

    fieldnames = reader.fieldnames

    mapping = {
        "ticker": _first_matching_header(fieldnames, ["ticker", "symbol", "instrument", "asset", "security"]),
        "action": _first_matching_header(fieldnames, ["transaction type", "type", "action", "side", "operation"]),
        "date": _first_matching_header(fieldnames, ["trade date", "date", "transaction date", "execution date"]),
        "quantity": _first_matching_header(fieldnames, ["quantity", "qty", "shares", "units"]),
        "price": _first_matching_header(fieldnames, ["price", "purchase price", "execution price", "unit price"]),
        "currency": _first_matching_header(fieldnames, ["currency", "curr", "ccy"]),
        "fee": _first_matching_header(fieldnames, ["fee", "commission", "cost", "transaction fee"]),
        "gross_amount": _first_matching_header(fieldnames, ["gross amount", "amount", "value", "total", "gross"]),
    }

    mapping_notes.append(
        f"{file_path.name}: detected delimiter='{dialect.delimiter}'"
    )
    mapping_notes.append(
        f"{file_path.name}: column mapping "
        + ", ".join(f"{k}={mapping[k] or 'None'}" for k in ["ticker", "action", "date", "quantity", "price", "currency", "fee", "gross_amount"])
    )

    broker_source = _infer_broker_source(file_path)

    for row_number, row in enumerate(reader, start=2):
        ticker_raw = row.get(mapping["ticker"], "") if mapping["ticker"] else ""
        action_raw = row.get(mapping["action"], "") if mapping["action"] else ""

        if not any((v or "").strip() for v in row.values()):
            continue

        ticker = normalize_ticker(ticker_raw)
        if not ticker:
            warnings.append(f"{file_path.name}:{row_number}: skipped row because no ticker")
            continue

        if not str(action_raw or "").strip():
            warnings.append(f"{file_path.name}:{row_number}: skipped row because no transaction type")
            continue

        action = normalize_action(str(action_raw))
        if action is None:
            warnings.append(
                f"{file_path.name}:{row_number}: skipped row because transaction type is not BUY/SELL ({action_raw})"
            )
            continue

        date_raw = row.get(mapping["date"], "") if mapping["date"] else ""
        tx_date = parse_date(str(date_raw))
        if tx_date is None:
            warnings.append(f"{file_path.name}:{row_number}: skipped row with invalid date ({date_raw})")
            continue

        qty_raw = row.get(mapping["quantity"], "") if mapping["quantity"] else ""
        quantity = parse_decimal(str(qty_raw))
        if quantity is None:
            warnings.append(f"{file_path.name}:{row_number}: skipped row with invalid numbers (quantity={qty_raw})")
            continue
        quantity = normalize_quantity_for_export(action, quantity)

        price = parse_decimal(str(row.get(mapping["price"], ""))) if mapping["price"] else None
        fee = parse_decimal(str(row.get(mapping["fee"], ""))) if mapping["fee"] else None
        gross_amount = parse_decimal(str(row.get(mapping["gross_amount"], ""))) if mapping["gross_amount"] else None

        currency = "USD"

        transactions.append(
            Transaction(
                source_file=file_path.name,
                broker_source=broker_source,
                ticker=ticker,
                action=action,
                date=tx_date,
                quantity=quantity,
                price=price,
                currency=currency,
                fee=fee,
                gross_amount=gross_amount,
                original_row_number=row_number,
            )
        )

    return FileExtractionResult(transactions, warnings, mapping_notes)


def group_by_ticker(transactions: Iterable[Transaction]) -> Dict[str, List[Transaction]]:
    grouped: Dict[str, List[Transaction]] = defaultdict(list)
    for tx in transactions:
        grouped[tx.ticker].append(tx)

    for ticker, items in grouped.items():
        items.sort(
            key=lambda t: (
                t.date,
                0 if t.action == "BUY" else 1,
                t.source_file.lower(),
                t.original_row_number,
            )
        )

    return dict(sorted(grouped.items(), key=lambda kv: kv[0]))


def _safe_pdf_name(ticker: str) -> str:
    safe = re.sub(r"[^A-Z0-9._-]", "_", ticker)
    safe = safe.strip("._")
    return safe or "UNKNOWN"


def _fmt_decimal(value: Optional[Decimal]) -> str:
    if value is None:
        return ""
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _compute_trade_value(tx: Transaction) -> Optional[Decimal]:
    if tx.price is None:
        return None
    return tx.quantity * tx.price


def _compute_open_position_value(lot: OpenPositionLot) -> Optional[Decimal]:
    if lot.price is None:
        return None
    return lot.quantity * lot.price


def compute_open_position_lots(transactions: List[Transaction]) -> List[OpenPositionLot]:
    buy_queues: Dict[str, List[OpenPositionLot]] = defaultdict(list)

    for tx in transactions:
        if tx.action == "BUY":
            buy_queues[tx.source_file].append(
                OpenPositionLot(
                    source_file=tx.source_file,
                    ticker=tx.ticker,
                    buy_date=tx.date,
                    quantity=tx.quantity,
                    price=tx.price,
                    currency=tx.currency,
                    fee=tx.fee,
                    original_row_number=tx.original_row_number,
                )
            )
            continue

        remaining_to_sell = tx.quantity
        lots = buy_queues[tx.source_file]
        while remaining_to_sell > 0 and lots:
            lot = lots[0]
            matched_qty = min(lot.quantity, remaining_to_sell)
            lot.quantity -= matched_qty
            remaining_to_sell -= matched_qty
            if lot.quantity <= 0:
                lots.pop(0)

    open_lots: List[OpenPositionLot] = []
    for lots in buy_queues.values():
        for lot in lots:
            if lot.quantity > 0:
                open_lots.append(lot)

    open_lots.sort(
        key=lambda lot: (
            lot.buy_date,
            lot.source_file.lower(),
            lot.original_row_number,
        ),
        reverse=True,
    )
    return open_lots


def compute_open_position_quantity(transactions: List[Transaction]) -> Decimal:
    total = Decimal("0")
    for lot in compute_open_position_lots(transactions):
        total += lot.quantity
    return total


YEAR_TABLE_COL_WIDTHS = [56, 36, 52, 54, 64, 38, 38, 128, 34]
OPEN_POSITIONS_COL_WIDTHS = [120, 80]


def build_pdf_for_ticker(
    ticker: str,
    transactions: List[Transaction],
    output_dir: Path,
    generated_at: datetime,
) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Indenter, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output_path = output_dir / f"{_safe_pdf_name(ticker)}.pdf"
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18,
        rightMargin=18,
        topMargin=20,
        bottomMargin=20,
        title=f"{ticker} trade history",
    )

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

    story = []
    years = sorted({tx.date.year for tx in transactions}, reverse=True)
    story.append(Paragraph(
        f"Ticker: {ticker} | Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        title_style,
    ))
    story.append(Spacer(1, 8))

    open_position_quantity = compute_open_position_quantity(transactions)
    story.append(Paragraph("Open Positions", year_style))
    story.append(Spacer(1, 4))
    year_table_left_offset = (doc.width - sum(YEAR_TABLE_COL_WIDTHS)) / 2

    open_rows = [[
        "Ticker",
        "Open Qty",
    ]]
    open_rows.append([
        ticker,
        _fmt_decimal(open_position_quantity),
    ])

    open_table = Table(
        open_rows,
        repeatRows=1,
        colWidths=OPEN_POSITIONS_COL_WIDTHS,
        hAlign="LEFT",
    )
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
    story.append(Indenter(left=year_table_left_offset, right=0))
    story.append(open_table)
    story.append(Indenter(left=-year_table_left_offset, right=0))
    story.append(Spacer(1, 10))

    for idx, year in enumerate(years):
        if idx > 0:
            story.append(Spacer(1, 10))

        story.append(Paragraph(f"Year: {year}", year_style))
        story.append(Spacer(1, 4))

        rows = [[
            "Date",
            "Action",
            "Qty",
            Paragraph("Unit Price", header_cell_style),
            Paragraph("Trade Value", header_cell_style),
            "Currency",
            "Fee",
            "Source",
            Paragraph("CSV Row", header_cell_style),
        ]]

        year_transactions = [tx for tx in transactions if tx.date.year == year]
        for tx in reversed(year_transactions):
            rows.append([
                tx.date.isoformat(),
                tx.action,
                _fmt_decimal(tx.quantity),
                _fmt_decimal(tx.price),
                _fmt_decimal(_compute_trade_value(tx)),
                tx.currency or "USD",
                _fmt_decimal(tx.fee),
                Paragraph(tx.source_file, source_cell_style),
                str(tx.original_row_number),
            ])

        table = Table(
            rows,
            repeatRows=1,
            colWidths=YEAR_TABLE_COL_WIDTHS,
        )
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

        story.append(table)

    doc.build(story)
    return output_path


def write_summary(output_dir: Path, grouped: Dict[str, List[Transaction]]) -> Path:
    summary_path = output_dir / "_export_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "ticker",
                "pdf_file",
                "transaction_count",
                "buy_count",
                "sell_count",
                "first_date",
                "last_date",
                "source_files",
            ]
        )

        for ticker, items in grouped.items():
            buy_count = sum(1 for t in items if t.action == "BUY")
            sell_count = sum(1 for t in items if t.action == "SELL")
            first_date = min(t.date for t in items).isoformat()
            last_date = max(t.date for t in items).isoformat()
            source_files = sorted({t.source_file for t in items})
            writer.writerow(
                [
                    ticker,
                    f"{_safe_pdf_name(ticker)}.pdf",
                    len(items),
                    buy_count,
                    sell_count,
                    first_date,
                    last_date,
                    ";".join(source_files),
                ]
            )
    return summary_path


def _write_warnings(output_dir: Path, warnings: List[str], mapping_notes: List[str]) -> Path:
    warnings_path = output_dir / "_export_warnings.txt"
    lines: List[str] = []
    lines.append("Export warnings and diagnostics")
    lines.append(datetime.now().strftime("Generated: %Y-%m-%d %H:%M:%S"))
    lines.append("")
    lines.append("Inferred column mappings and dialect")
    if mapping_notes:
        lines.extend(mapping_notes)
    else:
        lines.append("None")
    lines.append("")
    lines.append("Warnings")
    if warnings:
        lines.extend(warnings)
    else:
        lines.append("None")

    warnings_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return warnings_path


def main() -> int:
    _import_reportlab_or_fail()

    parser = argparse.ArgumentParser(
        description="Export one plain PDF per ticker with BUY/SELL transactions."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir

    try:
        csv_files = discover_csv_files(input_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)

    all_transactions: List[Transaction] = []
    all_warnings: List[str] = []
    all_mapping_notes: List[str] = []

    for csv_file in csv_files:
        result = extract_transactions_from_file(csv_file)
        all_transactions.extend(result.transactions)
        all_warnings.extend(result.warnings)
        all_mapping_notes.extend(result.mapping_notes)

    grouped = group_by_ticker(all_transactions)

    generated_at = datetime.now()
    created_pdfs: List[Path] = []
    for ticker, items in grouped.items():
        created_pdfs.append(build_pdf_for_ticker(ticker, items, output_dir, generated_at))

    summary_path = write_summary(output_dir, grouped)
    warnings_path = _write_warnings(output_dir, all_warnings, all_mapping_notes)

    print(f"CSV files read: {len(csv_files)}")
    print(f"Valid BUY/SELL transactions exported: {len(all_transactions)}")
    print(f"Ticker PDFs created: {len(created_pdfs)}")
    for pdf_path in created_pdfs:
        print(f"PDF: {pdf_path}")
    print(f"Summary: {summary_path}")
    print(f"Warnings: {warnings_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
