from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from stock_tax_report.domain.fx import FxRateBook
from stock_tax_report.domain.matches import MatchDetail, SellMatch
from stock_tax_report.domain.transactions import Transaction
from stock_tax_report.io.fx_loader import resolve_usd_to_czk_rate


def _compute_trade_value(quantity: Decimal, price: Optional[Decimal]) -> Optional[Decimal]:
    if price is None:
        return None
    return quantity * price


def _compute_trade_value_czk(
    quantity: Decimal,
    price: Optional[Decimal],
    value_date: date,
    fx_rate_book: FxRateBook,
) -> Optional[Decimal]:
    trade_value = _compute_trade_value(quantity, price)
    if trade_value is None:
        return None
    return trade_value * resolve_usd_to_czk_rate(fx_rate_book, value_date)


def _compute_match_pl_czk(match: MatchDetail, sell_date: date, fx_rate_book: FxRateBook) -> Decimal:
    buy_value_czk = _compute_trade_value_czk(match.matched_qty, match.buy_price, match.buy_date, fx_rate_book)
    sell_value_czk = _compute_trade_value_czk(match.matched_qty, match.sell_price, sell_date, fx_rate_book)
    assert buy_value_czk is not None
    assert sell_value_czk is not None
    return sell_value_czk - buy_value_czk


def _transaction_key(tx: Transaction) -> tuple[date, str, int]:
    return (tx.date, tx.source_file.lower(), tx.original_row_number)


def _buy_transaction_key(tx: Transaction) -> tuple[date, str, int]:
    return (tx.date, tx.source_file.lower(), tx.original_row_number)


def _buy_match_key(match: MatchDetail) -> tuple[date, str, int]:
    return (match.buy_date, match.buy_source_file.lower(), match.buy_row_number)


def _sell_match_key(sell_match: SellMatch) -> tuple[date, str, int]:
    return (sell_match.sell_date, sell_match.sell_source_file.lower(), sell_match.sell_row_number)
