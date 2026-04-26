from __future__ import annotations

import argparse
import csv
import re
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from typing import Dict, Iterable, List, Optional


DEFAULT_INPUT_DIR = Path(r"C:\DATA\PROJECTS\STOCKS_raw\.csv")
DEFAULT_OUTPUT_DIR = Path(r"C:\DATA\PROJECTS\STOCKS_raw\taxes\.pdf exports tax methods")
DEFAULT_TAX_METHODS_FILE = Path(r"C:\DATA\PROJECTS\STOCKS_raw\taxes\tax_methods.toml")

ALLOWED_METHODS = {"fifo", "lifo", "max_gains", "min_gains"}
QUANTITY_TOLERANCE = Decimal("0.00001")
METHOD_LABELS = {
    "fifo": "FIFO",
    "lifo": "LIFO",
    "max_gains": "max_gains",
    "min_gains": "min_gains",
}


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
class BuyLot:
    source_file: str
    ticker: str
    buy_date: date
    quantity: Decimal
    price: Decimal
    original_row_number: int


@dataclass
class MatchDetail:
    buy_date: date
    matched_qty: Decimal
    buy_price: Decimal
    sell_price: Decimal
    holding_period_days: int
    time_test_passed: bool
    total_pl: Decimal
    taxable_pl: Decimal
    buy_source_file: str
    buy_row_number: int


@dataclass
class SellMatch:
    sell_date: date
    sell_quantity: Decimal
    sell_price: Decimal
    sell_source_file: str
    sell_row_number: int
    method: str
    matches: List[MatchDetail]
    total_pl: Decimal
    total_taxable_pl: Decimal


@dataclass
class BuyUsage:
    sell_date: date
    matched_qty: Decimal
    sell_price: Decimal
    holding_period_days: int
    time_test_passed: bool
    total_pl: Decimal
    taxable_pl: Decimal
    sell_source_file: str
    sell_row_number: int


@dataclass
class YearSummary:
    total_income: Decimal
    total_pl: Optional[Decimal]
    taxable_pl: Optional[Decimal]
    over_three_year_pl: Optional[Decimal]


@dataclass
class IgnoredCurrentYearSell:
    sell_date: date
    sell_quantity: Decimal
    sell_price: Decimal
    sell_source_file: str
    sell_row_number: int


@dataclass
class TickerAnalysis:
    ticker: str
    years: List[int]
    transactions: List[Transaction]
    open_quantity: Decimal
    year_methods: Dict[int, str]
    sell_matches_by_year: Dict[int, List[SellMatch]]
    buy_usages_by_key: Dict[tuple[date, str, int], List[BuyUsage]]
    ignored_current_year_sells: List[IgnoredCurrentYearSell]
    source_files: List[str]


@dataclass
class TaxConfig:
    current_year: int
    methods_by_ticker: Dict[str, Dict[int, str]]


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
        "SPRZEDA\u017b": "SELL",
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


def _is_within_quantity_tolerance(value: Decimal) -> bool:
    return abs(value) <= QUANTITY_TOLERANCE


def _compute_trade_value(quantity: Decimal, price: Optional[Decimal]) -> Optional[Decimal]:
    if price is None:
        return None
    return quantity * price


def _source_ref(source_file: str, row_number: int) -> str:
    return f"{source_file}:{row_number}"


def _transaction_key(tx: Transaction) -> tuple[date, str, int]:
    return (tx.date, tx.source_file.lower(), tx.original_row_number)


def _sell_match_key(sell_match: SellMatch) -> tuple[date, str, int]:
    return (sell_match.sell_date, sell_match.sell_source_file.lower(), sell_match.sell_row_number)


def _buy_transaction_key(tx: Transaction) -> tuple[date, str, int]:
    return (tx.date, tx.source_file.lower(), tx.original_row_number)


def _buy_match_key(match: MatchDetail) -> tuple[date, str, int]:
    return (match.buy_date, match.buy_source_file.lower(), match.buy_row_number)


def _normalize_method_name(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in ALLOWED_METHODS:
        return normalized
    return None


def _parse_current_year(raw_value: object) -> int:
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip().isdigit():
        return int(raw_value.strip())
    raise ValueError("tax_methods.toml: 'current_year' must be an integer")


def load_tax_config(tax_methods_file: Path) -> TaxConfig:
    if not tax_methods_file.exists():
        raise FileNotFoundError(f"Tax methods file does not exist: {tax_methods_file}")

    try:
        data = tomllib.loads(tax_methods_file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"tax_methods.toml: invalid TOML ({exc})") from exc

    if "current_year" not in data:
        raise ValueError("tax_methods.toml: missing top-level 'current_year'")

    current_year = _parse_current_year(data["current_year"])
    methods_by_ticker: Dict[str, Dict[int, str]] = {}

    for key, value in data.items():
        if key == "current_year":
            continue

        if not isinstance(value, dict):
            raise ValueError(f"tax_methods.toml: section '{key}' must be a table")

        ticker = normalize_ticker(key)
        ticker_methods: Dict[int, str] = {}
        for year_key, method_value in value.items():
            year_text = str(year_key).strip()
            if not year_text.isdigit():
                raise ValueError(f"tax_methods.toml: ticker '{ticker}' has invalid year key '{year_key}'")

            method = _normalize_method_name(method_value)
            if method is None:
                raise ValueError(
                    f"tax_methods.toml: ticker '{ticker}' year '{year_text}' has invalid method '{method_value}'"
                )

            ticker_methods[int(year_text)] = method

        methods_by_ticker[ticker] = ticker_methods

    return TaxConfig(current_year=current_year, methods_by_ticker=methods_by_ticker)


def _infer_template_current_year(transactions: Iterable[Transaction]) -> int:
    years = [tx.date.year for tx in transactions]
    if not years:
        return datetime.now().year
    return max(years)


def build_template_text(grouped: Dict[str, List[Transaction]], current_year: int) -> str:
    lines: List[str] = []
    lines.append("current_year = %s" % current_year)
    lines.append("")

    for ticker, transactions in grouped.items():
        years = sorted({tx.date.year for tx in transactions if tx.date.year < current_year})
        if not years:
            continue

        lines.append(f"[{ticker}]")
        for year in years:
            lines.append(f'{year} = ""')
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_template_file(tax_methods_file: Path, grouped: Dict[str, List[Transaction]], current_year: int) -> Path:
    tax_methods_file.parent.mkdir(parents=True, exist_ok=True)
    tax_methods_file.write_text(build_template_text(grouped, current_year), encoding="utf-8")
    return tax_methods_file


def validate_tax_config(grouped: Dict[str, List[Transaction]], config: TaxConfig) -> List[str]:
    errors: List[str] = []

    for ticker, transactions in grouped.items():
        required_years = sorted({tx.date.year for tx in transactions if tx.date.year < config.current_year})
        ticker_methods = config.methods_by_ticker.get(ticker, {})
        for year in required_years:
            if year not in ticker_methods:
                errors.append(f"ticker '{ticker}' is missing tax method for year {year}")

    return errors


def add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def is_time_test_passed(buy_date: date, sell_date: date) -> bool:
    return sell_date > add_years(buy_date, 3)


def _holding_period_days(buy_date: date, sell_date: date) -> int:
    return (sell_date - buy_date).days


def _lot_identity_key(lot: BuyLot) -> tuple[date, str, int]:
    return (lot.buy_date, lot.source_file.lower(), lot.original_row_number)


def _lot_taxable_unit_pl(lot: BuyLot, sell_tx: Transaction) -> Decimal:
    if is_time_test_passed(lot.buy_date, sell_tx.date):
        return Decimal("0")
    return sell_tx.price - lot.price


def _ordered_lots_for_method(lots: List[BuyLot], sell_tx: Transaction, method: str) -> List[BuyLot]:
    available = [lot for lot in lots if lot.quantity > 0]

    if method == "fifo":
        return sorted(available, key=_lot_identity_key)
    if method == "lifo":
        return sorted(available, key=_lot_identity_key, reverse=True)
    if method == "max_gains":
        return sorted(
            available,
            key=lambda lot: (-_lot_taxable_unit_pl(lot, sell_tx),) + _lot_identity_key(lot),
        )
    if method == "min_gains":
        return sorted(
            available,
            key=lambda lot: (_lot_taxable_unit_pl(lot, sell_tx),) + _lot_identity_key(lot),
        )
    raise ValueError(f"Unsupported tax method: {method}")


def _ensure_transaction_has_price(tx: Transaction) -> Decimal:
    if tx.price is None:
        raise ValueError(
            f"{tx.ticker}: transaction {tx.source_file}:{tx.original_row_number} on {tx.date.isoformat()} has no price"
        )
    return tx.price


def match_sell_transaction(remaining_lots: List[BuyLot], sell_tx: Transaction, method: str) -> SellMatch:
    sell_price = _ensure_transaction_has_price(sell_tx)
    remaining_quantity = sell_tx.quantity
    total_available = sum((lot.quantity for lot in remaining_lots), Decimal("0"))
    shortfall = remaining_quantity - total_available
    if shortfall > QUANTITY_TOLERANCE:
        raise ValueError(
            f"{sell_tx.ticker}: SELL {sell_tx.source_file}:{sell_tx.original_row_number} on {sell_tx.date.isoformat()} "
            f"for qty {_fmt_decimal(sell_tx.quantity)} exceeds available BUY lots {_fmt_decimal(total_available)}"
        )

    ordered_lots = _ordered_lots_for_method(remaining_lots, sell_tx, method)
    matches: List[MatchDetail] = []

    for lot in ordered_lots:
        if remaining_quantity <= 0:
            break
        if lot.quantity <= 0:
            continue

        matched_qty = min(lot.quantity, remaining_quantity)
        time_test_passed = is_time_test_passed(lot.buy_date, sell_tx.date)
        total_pl = (sell_price - lot.price) * matched_qty
        taxable_pl = Decimal("0")
        if not time_test_passed:
            taxable_pl = total_pl

        matches.append(
            MatchDetail(
                buy_date=lot.buy_date,
                matched_qty=matched_qty,
                buy_price=lot.price,
                sell_price=sell_price,
                holding_period_days=_holding_period_days(lot.buy_date, sell_tx.date),
                time_test_passed=time_test_passed,
                total_pl=total_pl,
                taxable_pl=taxable_pl,
                buy_source_file=lot.source_file,
                buy_row_number=lot.original_row_number,
            )
        )

        lot.quantity -= matched_qty
        remaining_quantity -= matched_qty

    if remaining_quantity > 0 and _is_within_quantity_tolerance(remaining_quantity) and matches:
        last_match = matches[-1]
        last_match.matched_qty += remaining_quantity
        last_match.total_pl += (sell_price - last_match.buy_price) * remaining_quantity
        if not last_match.time_test_passed:
            last_match.taxable_pl += (sell_price - last_match.buy_price) * remaining_quantity
        remaining_quantity = Decimal("0")

    if remaining_quantity > 0:
        raise ValueError(
            f"{sell_tx.ticker}: SELL {sell_tx.source_file}:{sell_tx.original_row_number} on {sell_tx.date.isoformat()} "
            f"could not be fully matched, remaining qty {_fmt_decimal(remaining_quantity)}"
        )

    remaining_lots[:] = [lot for lot in remaining_lots if lot.quantity > 0]
    total_pl = sum((match.total_pl for match in matches), Decimal("0"))
    total_taxable_pl = sum((match.taxable_pl for match in matches), Decimal("0"))

    return SellMatch(
        sell_date=sell_tx.date,
        sell_quantity=sell_tx.quantity,
        sell_price=sell_price,
        sell_source_file=sell_tx.source_file,
        sell_row_number=sell_tx.original_row_number,
        method=method,
        matches=matches,
        total_pl=total_pl,
        total_taxable_pl=total_taxable_pl,
    )


def analyze_ticker(ticker: str, transactions: List[Transaction], config: TaxConfig) -> TickerAnalysis:
    years = sorted({tx.date.year for tx in transactions}, reverse=True)
    remaining_lots: List[BuyLot] = []
    sell_matches_by_year: Dict[int, List[SellMatch]] = defaultdict(list)
    buy_usages_by_key: Dict[tuple[date, str, int], List[BuyUsage]] = defaultdict(list)
    ignored_current_year_sells: List[IgnoredCurrentYearSell] = []

    for tx in transactions:
        price = _ensure_transaction_has_price(tx)

        if tx.action == "BUY":
            remaining_lots.append(
                BuyLot(
                    source_file=tx.source_file,
                    ticker=ticker,
                    buy_date=tx.date,
                    quantity=tx.quantity,
                    price=price,
                    original_row_number=tx.original_row_number,
                )
            )
            continue

        if tx.date.year == config.current_year:
            ignored_current_year_sells.append(
                IgnoredCurrentYearSell(
                    sell_date=tx.date,
                    sell_quantity=tx.quantity,
                    sell_price=price,
                    sell_source_file=tx.source_file,
                    sell_row_number=tx.original_row_number,
                )
            )
            continue

        method = config.methods_by_ticker[ticker][tx.date.year]
        sell_match = match_sell_transaction(remaining_lots, tx, method)
        sell_matches_by_year[tx.date.year].append(sell_match)

        for match in sell_match.matches:
            buy_usages_by_key[_buy_match_key(match)].append(
                BuyUsage(
                    sell_date=sell_match.sell_date,
                    matched_qty=match.matched_qty,
                    sell_price=match.sell_price,
                    holding_period_days=match.holding_period_days,
                    time_test_passed=match.time_test_passed,
                    total_pl=match.total_pl,
                    taxable_pl=match.taxable_pl,
                    sell_source_file=sell_match.sell_source_file,
                    sell_row_number=sell_match.sell_row_number,
                )
            )

    open_quantity = sum((lot.quantity for lot in remaining_lots), Decimal("0"))
    if _is_within_quantity_tolerance(open_quantity):
        open_quantity = Decimal("0")
    year_methods = {
        year: config.methods_by_ticker[ticker][year]
        for year in sorted(config.methods_by_ticker.get(ticker, {}))
        if year < config.current_year
    }

    return TickerAnalysis(
        ticker=ticker,
        years=years,
        transactions=list(transactions),
        open_quantity=open_quantity,
        year_methods=year_methods,
        sell_matches_by_year=dict(sell_matches_by_year),
        buy_usages_by_key={
            key: sorted(value, key=lambda item: (item.sell_date, item.sell_source_file.lower(), item.sell_row_number))
            for key, value in buy_usages_by_key.items()
        },
        ignored_current_year_sells=ignored_current_year_sells,
        source_files=sorted({tx.source_file for tx in transactions}),
    )


OPEN_POSITIONS_COL_WIDTHS = [120, 80]
YEAR_HISTORY_COL_WIDTHS = [122, 42, 52, 56, 60, 104, 112]


def _format_holding_period(days: int) -> str:
    return f"{days} d"


def _format_match_status(time_test_passed: bool, holding_period_days: int) -> str:
    return f"{'PASS' if time_test_passed else 'FAIL'} | {_format_holding_period(holding_period_days)}"


def _compute_year_summary(analysis: TickerAnalysis, year: int, current_year: int) -> YearSummary:
    year_sells = [tx for tx in analysis.transactions if tx.date.year == year and tx.action == "SELL"]
    total_income = sum(((_compute_trade_value(tx.quantity, tx.price) or Decimal("0")) for tx in year_sells), Decimal("0"))

    if year >= current_year:
        return YearSummary(
            total_income=total_income,
            total_pl=None,
            taxable_pl=None,
            over_three_year_pl=None,
        )

    sell_matches = analysis.sell_matches_by_year.get(year, [])
    total_pl = sum((sell_match.total_pl for sell_match in sell_matches), Decimal("0"))
    taxable_pl = sum((sell_match.total_taxable_pl for sell_match in sell_matches), Decimal("0"))
    over_three_year_pl = sum(
        (match.total_pl for sell_match in sell_matches for match in sell_match.matches if match.time_test_passed),
        Decimal("0"),
    )
    return YearSummary(
        total_income=total_income,
        total_pl=total_pl,
        taxable_pl=taxable_pl,
        over_three_year_pl=over_three_year_pl,
    )


def _build_year_summary_table(summary: YearSummary):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    rows = [[
        "Income",
        "Profit/Loss",
        "3 years rule PASS (P/L)",
        "3 years rule FAIL (P/L)",
    ]]
    rows.append([
        _fmt_decimal(summary.total_income),
        _fmt_decimal(summary.total_pl),
        _fmt_decimal(summary.over_three_year_pl),
        _fmt_decimal(summary.taxable_pl),
    ])

    table = Table(rows, repeatRows=1, colWidths=[115, 115, 115, 115], hAlign="LEFT")
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


def _sum_optional_decimals(values: List[Optional[Decimal]]) -> Optional[Decimal]:
    present_values = [value for value in values if value is not None]
    if not present_values:
        return None
    return sum(present_values, Decimal("0"))


def _compute_aggregate_year_summaries(
    analyses: List[TickerAnalysis],
    current_year: int,
) -> Dict[int, YearSummary]:
    years = sorted({year for analysis in analyses for year in analysis.years}, reverse=True)
    aggregated: Dict[int, YearSummary] = {}

    for year in years:
        summaries = [_compute_year_summary(analysis, year, current_year) for analysis in analyses if year in analysis.years]
        aggregated[year] = YearSummary(
            total_income=sum((summary.total_income for summary in summaries), Decimal("0")),
            total_pl=_sum_optional_decimals([summary.total_pl for summary in summaries]),
            taxable_pl=_sum_optional_decimals([summary.taxable_pl for summary in summaries]),
            over_three_year_pl=_sum_optional_decimals([summary.over_three_year_pl for summary in summaries]),
        )

    return aggregated


def build_all_tickers_year_summary_pdf(
    analyses: List[TickerAnalysis],
    output_dir: Path,
    generated_at: datetime,
    current_year: int,
) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
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

    aggregated = _compute_aggregate_year_summaries(analyses, current_year)
    rows = [[
        "Year",
        "Income",
        "Profit/Loss",
        "3 years rule PASS (P/L)",
        "3 years rule FAIL (P/L)",
    ]]

    for year in sorted(aggregated, reverse=True):
        summary = aggregated[year]
        rows.append([
            str(year),
            _fmt_decimal(summary.total_income),
            _fmt_decimal(summary.total_pl),
            _fmt_decimal(summary.over_three_year_pl),
            _fmt_decimal(summary.taxable_pl),
        ])

    table = Table(rows, repeatRows=1, colWidths=[54, 95, 95, 120, 120], hAlign="LEFT")
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
            f"All Tickers Year Summary | Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
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


def _build_year_history_table(
    analysis: TickerAnalysis,
    year: int,
    current_year: int,
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
        Paragraph("Value", header_style),
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

        if year == current_year and tx.action == "SELL":
            block_label = f"{tx.date.isoformat()} SELL (ignored)"
            taxable_pl = None

        rows.append([
            Paragraph(block_label, block_style),
            _fmt_decimal(tx.quantity),
            _fmt_decimal(tx.price),
            _fmt_decimal(_compute_trade_value(tx.quantity, tx.price)),
            _fmt_decimal(taxable_pl),
            "",
            Paragraph(_source_ref(tx.source_file, tx.original_row_number), body_style),
        ])
        if tx.action == "SELL":
            sell_main_row_indexes.append(len(rows) - 1)

        if sell_match is not None:
            for lot_number, match in enumerate(sell_match.matches, start=1):
                rows.append([
                    Paragraph(f"* Lot #{lot_number} | Bought {match.buy_date.isoformat()}", lot_style),
                    _fmt_decimal(match.matched_qty),
                    _fmt_decimal(match.buy_price),
                    _fmt_decimal(_compute_trade_value(match.matched_qty, match.buy_price)),
                    _fmt_decimal(match.total_pl),
                    Paragraph(_format_match_status(match.time_test_passed, match.holding_period_days), lot_style),
                    Paragraph(_source_ref(match.buy_source_file, match.buy_row_number), lot_style),
                ])
                detail_row_indexes.append(len(rows) - 1)
        elif buy_usages:
            for usage_number, usage in enumerate(buy_usages, start=1):
                rows.append([
                    Paragraph(f"* Split #{usage_number} | Sold {usage.sell_date.isoformat()}", lot_style),
                    _fmt_decimal(usage.matched_qty),
                    _fmt_decimal(usage.sell_price),
                    _fmt_decimal(_compute_trade_value(usage.matched_qty, usage.sell_price)),
                    _fmt_decimal(usage.total_pl),
                    Paragraph(_format_match_status(usage.time_test_passed, usage.holding_period_days), lot_style),
                    Paragraph(_source_ref(usage.sell_source_file, usage.sell_row_number), lot_style),
                ])
                detail_row_indexes.append(len(rows) - 1)
        elif year == current_year and tx.action == "SELL":
            rows.append([
                Paragraph("* Current year | No tax matching", lot_style),
                "",
                Paragraph("Not included", lot_style),
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
) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
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
    exported_styles = {
        "header_cell_style": header_cell_style,
        "source_cell_style": source_cell_style,
        "buy_block_cell_style": buy_block_cell_style,
        "sell_block_cell_style": sell_block_cell_style,
        "lot_cell_style": lot_cell_style,
    }

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
            heading = f"{heading} | Method: {METHOD_LABELS[analysis.year_methods[year]]}"
        year_summary_table = _build_year_summary_table(_compute_year_summary(analysis, year, current_year))
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

        story.append(_build_year_history_table(analysis, year, current_year, exported_styles))
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


def write_summary(output_dir: Path, analyses: List[TickerAnalysis]) -> Path:
    summary_path = output_dir / "_export_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ticker",
                "pdf_file",
                "year_count",
                "sell_count",
                "ignored_current_year_sell_count",
                "open_qty",
                "source_files",
            ]
        )

        for analysis in analyses:
            sell_count = sum(len(items) for items in analysis.sell_matches_by_year.values())
            writer.writerow(
                [
                    analysis.ticker,
                    f"{_safe_pdf_name(analysis.ticker)}.pdf",
                    len(analysis.years),
                    sell_count,
                    len(analysis.ignored_current_year_sells),
                    _fmt_decimal(analysis.open_quantity),
                    ";".join(analysis.source_files),
                ]
            )

    return summary_path


def write_warnings(
    output_dir: Path,
    parser_warnings: List[str],
    mapping_notes: List[str],
    analyses: List[TickerAnalysis],
) -> Path:
    warnings_path = output_dir / "_export_warnings.txt"
    lines: List[str] = []
    lines.append("Export warnings and diagnostics")
    lines.append(datetime.now().strftime("Generated: %Y-%m-%d %H:%M:%S"))
    lines.append("")
    lines.append("Inferred column mappings and dialect")
    lines.extend(mapping_notes or ["None"])
    lines.append("")
    lines.append("Warnings")
    lines.extend(parser_warnings or ["None"])
    lines.append("")
    lines.append("Ignored current-year SELL transactions")

    ignored_lines: List[str] = []
    for analysis in analyses:
        for item in analysis.ignored_current_year_sells:
            ignored_lines.append(
                f"{analysis.ticker}: {item.sell_date.isoformat()} qty={_fmt_decimal(item.sell_quantity)} "
                f"source={item.sell_source_file}:{item.sell_row_number}"
            )

    lines.extend(ignored_lines or ["None"])
    warnings_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return warnings_path


def _clear_previous_exports(output_dir: Path) -> None:
    for pdf_path in output_dir.glob("*.pdf"):
        pdf_path.unlink(missing_ok=True)

    for artifact_name in ["_export_summary.csv", "_export_warnings.txt"]:
        (output_dir / artifact_name).unlink(missing_ok=True)


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
        created_pdfs.append(build_pdf_for_ticker(analysis, args.output_dir, generated_at, config.current_year))
    all_tickers_summary_pdf = build_all_tickers_year_summary_pdf(analyses, args.output_dir, generated_at, config.current_year)

    summary_path = write_summary(args.output_dir, analyses)
    warnings_path = write_warnings(args.output_dir, all_warnings, all_mapping_notes, analyses)

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
