from __future__ import annotations

from decimal import Decimal
from typing import List

from stock_tax_report.domain.lots import BuyLot
from stock_tax_report.domain.matches import MatchDetail, SellMatch
from stock_tax_report.domain.transactions import Transaction
from stock_tax_report.matching.common import (
    QUANTITY_TOLERANCE,
    _ensure_transaction_has_price,
    _fmt_decimal,
    _holding_period_days,
    _is_within_quantity_tolerance,
    _ordered_lots_for_method,
    is_time_test_passed,
)


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
