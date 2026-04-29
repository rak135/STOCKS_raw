from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from stock_tax_report.domain.transactions import FileExtractionResult, Transaction
from stock_tax_report.io.parsing import (
    normalize_action,
    normalize_quantity_for_export,
    normalize_ticker,
    parse_date,
    parse_decimal,
)


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

    mapping_notes.append(f"{file_path.name}: detected delimiter='{dialect.delimiter}'")
    mapping_notes.append(
        f"{file_path.name}: column mapping "
        + ", ".join(
            f"{key}={mapping[key] or 'None'}"
            for key in ["ticker", "action", "date", "quantity", "price", "currency", "fee", "gross_amount"]
        )
    )

    broker_source = _infer_broker_source(file_path)

    for row_number, row in enumerate(reader, start=2):
        ticker_raw = row.get(mapping["ticker"], "") if mapping["ticker"] else ""
        action_raw = row.get(mapping["action"], "") if mapping["action"] else ""

        if not any((value or "").strip() for value in row.values()):
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

    for items in grouped.values():
        items.sort(
            key=lambda tx: (
                tx.date,
                0 if tx.action == "BUY" else 1,
                tx.source_file.lower(),
                tx.original_row_number,
            )
        )

    return dict(sorted(grouped.items(), key=lambda item: item[0]))
