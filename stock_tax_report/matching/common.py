from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List

from stock_tax_report.domain.lots import BuyLot
from stock_tax_report.domain.transactions import Transaction


QUANTITY_TOLERANCE = Decimal("0.00001")


def _fmt_decimal(value: Decimal, places: int = 2) -> str:
    quantizer = Decimal("1").scaleb(-places)
    rounded = value.quantize(quantizer, rounding=ROUND_HALF_UP)
    return format(rounded, f".{places}f")


def add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def is_time_test_passed(buy_date: date, sell_date: date) -> bool:
    return sell_date > add_years(buy_date, 3)


def _holding_period_days(buy_date: date, sell_date: date) -> int:
    return (sell_date - buy_date).days


def _is_within_quantity_tolerance(value: Decimal) -> bool:
    return abs(value) <= QUANTITY_TOLERANCE


def _ensure_transaction_has_price(tx: Transaction) -> Decimal:
    if tx.price is None:
        raise ValueError(
            f"{tx.ticker}: transaction {tx.source_file}:{tx.original_row_number} on {tx.date.isoformat()} has no price"
        )
    return tx.price


def _lot_identity_key(lot: BuyLot) -> tuple[date, str, int]:
    return (lot.buy_date, lot.source_file.lower(), lot.original_row_number)


def _lot_taxable_unit_pl(lot: BuyLot, sell_tx: Transaction) -> Decimal:
    if is_time_test_passed(lot.buy_date, sell_tx.date):
        return Decimal("0")
    return sell_tx.price - lot.price


def _lot_total_unit_pl(lot: BuyLot, sell_tx: Transaction) -> Decimal:
    return sell_tx.price - lot.price


def _copy_buy_lot(lot: BuyLot) -> BuyLot:
    return BuyLot(
        source_file=lot.source_file,
        ticker=lot.ticker,
        buy_date=lot.buy_date,
        quantity=lot.quantity,
        price=lot.price,
        original_row_number=lot.original_row_number,
        available_order=lot.available_order,
    )


def _create_buy_lot_from_transaction(tx: Transaction, available_order: int = -1) -> BuyLot:
    return BuyLot(
        source_file=tx.source_file,
        ticker=tx.ticker,
        buy_date=tx.date,
        quantity=tx.quantity,
        price=_ensure_transaction_has_price(tx),
        original_row_number=tx.original_row_number,
        available_order=available_order,
    )


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
    if method == "time_test_max":
        return sorted(
            available,
            key=lambda lot: (
                0 if is_time_test_passed(lot.buy_date, sell_tx.date) else 1,
                -_lot_total_unit_pl(lot, sell_tx) if is_time_test_passed(lot.buy_date, sell_tx.date) else _lot_taxable_unit_pl(lot, sell_tx),
            )
            + _lot_identity_key(lot),
        )
    raise ValueError(f"Unsupported tax method: {method}")
