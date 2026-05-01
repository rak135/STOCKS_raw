from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, List

from stock_tax_report.analysis.trade_value import _buy_match_key
from stock_tax_report.domain.analysis import TickerAnalysis
from stock_tax_report.domain.config import TaxConfig
from stock_tax_report.domain.lots import BuyLot
from stock_tax_report.domain.matches import BuyUsage, IgnoredCurrentYearSell, SellMatch
from stock_tax_report.domain.transactions import Transaction
from stock_tax_report.matching.common import (
    _create_buy_lot_from_transaction,
    _ensure_transaction_has_price,
    _is_within_quantity_tolerance,
)
from stock_tax_report.matching.standard import match_sell_transaction
from stock_tax_report.matching.time_test_max import _build_time_test_max_sell_matches


def analyze_ticker(ticker: str, transactions: List[Transaction], config: TaxConfig) -> TickerAnalysis:
    years = sorted({tx.date.year for tx in transactions}, reverse=True)
    remaining_lots: List[BuyLot] = []
    sell_matches_by_year: Dict[int, List[SellMatch]] = defaultdict(list)
    buy_usages_by_key: Dict[tuple[date, str, int], List[BuyUsage]] = defaultdict(list)
    ignored_current_year_sells: List[IgnoredCurrentYearSell] = []

    transactions_by_year: Dict[int, List[Transaction]] = defaultdict(list)
    for tx in transactions:
        transactions_by_year[tx.date.year].append(tx)

    for year in sorted(transactions_by_year):
        year_transactions = transactions_by_year[year]

        if year == config.current_year:
            for tx in year_transactions:
                price = _ensure_transaction_has_price(tx)
                if tx.action == "BUY":
                    remaining_lots.append(_create_buy_lot_from_transaction(tx))
                else:
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

        year_sells = [tx for tx in year_transactions if tx.action == "SELL"]
        method = config.methods_by_ticker[ticker][year]

        if year_sells and method == "time_test_max":
            sell_matches, remaining_lots = _build_time_test_max_sell_matches(ticker, remaining_lots, year_transactions)
            sell_matches_by_year[year].extend(sell_matches)
        else:
            for tx in year_transactions:
                price = _ensure_transaction_has_price(tx)
                if tx.action == "BUY":
                    remaining_lots.append(_create_buy_lot_from_transaction(tx))
                    continue

                sell_match = match_sell_transaction(remaining_lots, tx, method)
                sell_matches_by_year[year].append(sell_match)

        for sell_match in sell_matches_by_year.get(year, []):
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
