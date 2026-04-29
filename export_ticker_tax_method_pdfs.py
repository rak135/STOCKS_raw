from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from stock_tax_report.domain.analysis import TickerAnalysis, YearSummary
from stock_tax_report.domain.config import TaxConfig
from stock_tax_report.domain.fx import FxConfig, FxRateBook
from stock_tax_report.domain.lots import BuyLot
from stock_tax_report.domain.matches import (
    BuyUsage,
    IgnoredCurrentYearSell,
    MatchDetail,
    SellMatch,
)
from stock_tax_report.domain.transactions import FileExtractionResult, Transaction
from stock_tax_report.io.csv_discovery import discover_csv_files
from stock_tax_report.io.csv_parser import (
    detect_dialect,
    extract_transactions_from_file,
    group_by_ticker,
)
from stock_tax_report.io.fx_loader import (
    _load_cnb_daily_usd_rates,
    _load_all_cnb_daily_usd_rates,
    load_fx_rate_book,
    resolve_usd_to_czk_rate,
)
from stock_tax_report.io.parsing import (
    normalize_action,
    normalize_quantity_for_export,
    normalize_ticker,
    parse_date,
    parse_decimal,
)
from stock_tax_report.io.tax_config_loader import (
    ALLOWED_FX_MODES,
    ALLOWED_METHODS,
    _infer_template_current_year,
    build_template_text,
    load_tax_config,
    validate_tax_config,
    write_template_file,
)


DEFAULT_INPUT_DIR = Path(r"C:\DATA\PROJECTS\STOCKS_raw\.csv")
DEFAULT_OUTPUT_DIR = Path(r"C:\DATA\PROJECTS\STOCKS_raw\.pdf exports tax methods")
DEFAULT_TAX_METHODS_FILE = Path(r"C:\DATA\PROJECTS\STOCKS_raw\tax_methods.toml")

QUANTITY_TOLERANCE = Decimal("0.00001")
METHOD_LABELS = {
    "fifo": "FIFO",
    "lifo": "LIFO",
    "max_gains": "max_gains",
    "min_gains": "min_gains",
    "time_test_max": "TIME_TEST_MAX",
}
FLOW_SCALE = Decimal("100000")


def _import_reportlab_or_fail() -> None:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        print("Missing dependency: reportlab", file=sys.stderr)
        print("Install with: py -m pip install reportlab", file=sys.stderr)
        raise SystemExit(2)


@dataclass
class SellCandidate:
    transaction: Transaction
    order_index: int


@dataclass
class _FlowEdge:
    to_node: int
    reverse_index: int
    capacity: int
    cost: int


def _safe_pdf_name(ticker: str) -> str:
    safe = re.sub(r"[^A-Z0-9._-]", "_", ticker)
    safe = safe.strip("._")
    return safe or "UNKNOWN"


def _fmt_decimal(value: Optional[Decimal], places: int = 2) -> str:
    if value is None:
        return ""
    quantizer = Decimal("1").scaleb(-places)
    rounded = value.quantize(quantizer, rounding=ROUND_HALF_UP)
    return format(rounded, f".{places}f")


def _fmt_usd_czk_pair(usd_value: Optional[Decimal], czk_value: Optional[Decimal]) -> str:
    if usd_value is None and czk_value is None:
        return ""
    if czk_value is None:
        return _fmt_decimal(usd_value)
    if usd_value is None:
        return _fmt_decimal(czk_value)
    return f"{_fmt_decimal(usd_value)} / {_fmt_decimal(czk_value)}"


def _year_fx_label(year: int, current_year: int, fx_rate_book: FxRateBook) -> str:
    if year >= current_year:
        return "FX=n/a"
    return f"FX={fx_rate_book.mode}"


def _is_within_quantity_tolerance(value: Decimal) -> bool:
    return abs(value) <= QUANTITY_TOLERANCE


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


def _lot_total_unit_pl(lot: BuyLot, sell_tx: Transaction) -> Decimal:
    return sell_tx.price - lot.price


def _decimal_to_flow_int(value: Decimal) -> int:
    return int((value * FLOW_SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def _flow_int_to_decimal(value: int) -> Decimal:
    return Decimal(value) / FLOW_SCALE


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


def _add_flow_edge(graph: List[List[_FlowEdge]], from_node: int, to_node: int, capacity: int, cost: int) -> _FlowEdge:
    forward = _FlowEdge(to_node=to_node, reverse_index=len(graph[to_node]), capacity=capacity, cost=cost)
    backward = _FlowEdge(to_node=from_node, reverse_index=len(graph[from_node]), capacity=0, cost=-cost)
    graph[from_node].append(forward)
    graph[to_node].append(backward)
    return forward


def _min_cost_flow(graph: List[List[_FlowEdge]], source: int, sink: int, required_flow: int) -> tuple[int, int]:
    total_flow = 0
    total_cost = 0
    node_count = len(graph)

    while total_flow < required_flow:
        distances = [None] * node_count
        in_queue = [False] * node_count
        previous_node = [-1] * node_count
        previous_edge_index = [-1] * node_count
        queue = [source]
        distances[source] = 0
        in_queue[source] = True

        while queue:
            node = queue.pop(0)
            in_queue[node] = False
            current_distance = distances[node]
            if current_distance is None:
                continue

            for edge_index, edge in enumerate(graph[node]):
                if edge.capacity <= 0:
                    continue
                next_distance = current_distance + edge.cost
                if distances[edge.to_node] is None or next_distance < distances[edge.to_node]:
                    distances[edge.to_node] = next_distance
                    previous_node[edge.to_node] = node
                    previous_edge_index[edge.to_node] = edge_index
                    if not in_queue[edge.to_node]:
                        queue.append(edge.to_node)
                        in_queue[edge.to_node] = True

        if distances[sink] is None:
            break

        augment = required_flow - total_flow
        node = sink
        while node != source:
            prev_node = previous_node[node]
            prev_edge = graph[prev_node][previous_edge_index[node]]
            augment = min(augment, prev_edge.capacity)
            node = prev_node

        node = sink
        while node != source:
            prev_node = previous_node[node]
            edge_index = previous_edge_index[node]
            edge = graph[prev_node][edge_index]
            edge.capacity -= augment
            reverse_edge = graph[node][edge.reverse_index]
            reverse_edge.capacity += augment
            node = prev_node

        total_flow += augment
        total_cost += augment * distances[sink]

    return total_flow, total_cost


def _build_time_test_max_sell_matches(
    ticker: str,
    remaining_lots: List[BuyLot],
    year_transactions: List[Transaction],
) -> tuple[List[SellMatch], List[BuyLot]]:
    lot_candidates = [_copy_buy_lot(lot) for lot in remaining_lots]
    sells: List[SellCandidate] = []

    for order_index, tx in enumerate(year_transactions):
        if tx.action == "BUY":
            lot_candidates.append(_create_buy_lot_from_transaction(tx, available_order=order_index))
        else:
            sells.append(SellCandidate(transaction=tx, order_index=order_index))

    if not sells:
        return [], [lot for lot in lot_candidates if lot.quantity > 0]

    total_required_flow = sum((_decimal_to_flow_int(sell.transaction.quantity) for sell in sells), 0)
    if total_required_flow <= 0:
        return [], [lot for lot in lot_candidates if lot.quantity > 0]

    unit_taxable_bounds: List[int] = []
    sell_qty_ints: List[int] = []
    for sell in sells:
        sell_tx = sell.transaction
        sell_qty_int = _decimal_to_flow_int(sell_tx.quantity)
        sell_qty_ints.append(sell_qty_int)
        candidate_unit_costs: List[int] = []
        for lot in lot_candidates:
            if lot.available_order >= 0 and lot.available_order >= sell.order_index:
                continue
            candidate_unit_costs.append(abs(_decimal_to_flow_int(_lot_taxable_unit_pl(lot, sell_tx))))
        unit_taxable_bounds.append(max(candidate_unit_costs) if candidate_unit_costs else 0)

    max_secondary_span = sum((unit_taxable_bounds[idx] * sell_qty_ints[idx] * 2 for idx in range(len(sells))), 0)
    primary_multiplier = max_secondary_span + 1

    node_count = 2 + len(lot_candidates) + len(sells)
    source = 0
    sink = node_count - 1
    lot_offset = 1
    sell_offset = 1 + len(lot_candidates)
    graph: List[List[_FlowEdge]] = [[] for _ in range(node_count)]
    edge_map: Dict[tuple[int, int], _FlowEdge] = {}

    for lot_index, lot in enumerate(lot_candidates):
        lot_qty_int = _decimal_to_flow_int(lot.quantity)
        _add_flow_edge(graph, source, lot_offset + lot_index, lot_qty_int, 0)

    for sell_index, sell in enumerate(sells):
        sell_qty_int = _decimal_to_flow_int(sell.transaction.quantity)
        _add_flow_edge(graph, sell_offset + sell_index, sink, sell_qty_int, 0)

    for lot_index, lot in enumerate(lot_candidates):
        lot_qty_int = _decimal_to_flow_int(lot.quantity)
        if lot_qty_int <= 0:
            continue

        for sell_index, sell in enumerate(sells):
            if lot.available_order >= 0 and lot.available_order >= sell.order_index:
                continue

            sell_tx = sell.transaction
            edge_capacity = min(lot_qty_int, _decimal_to_flow_int(sell_tx.quantity))
            if edge_capacity <= 0:
                continue

            if is_time_test_passed(lot.buy_date, sell_tx.date):
                unit_total_pl_int = _decimal_to_flow_int(_lot_total_unit_pl(lot, sell_tx))
                edge_cost = -(primary_multiplier * unit_total_pl_int)
            else:
                edge_cost = _decimal_to_flow_int(_lot_taxable_unit_pl(lot, sell_tx))

            edge_map[(lot_index, sell_index)] = _add_flow_edge(
                graph,
                lot_offset + lot_index,
                sell_offset + sell_index,
                edge_capacity,
                edge_cost,
            )

    flowed, _ = _min_cost_flow(graph, source, sink, total_required_flow)
    if flowed != total_required_flow:
        available_qty = _flow_int_to_decimal(sum((_decimal_to_flow_int(lot.quantity) for lot in lot_candidates), 0))
        required_qty = _flow_int_to_decimal(total_required_flow)
        raise ValueError(
            f"{ticker}: TIME_TEST_MAX could not fully match yearly sells, available qty {_fmt_decimal(available_qty)} "
            f"required qty {_fmt_decimal(required_qty)}"
        )

    matches_by_sell_index: Dict[int, List[MatchDetail]] = defaultdict(list)
    for (lot_index, sell_index), edge in edge_map.items():
        reverse_edge = graph[edge.to_node][edge.reverse_index]
        matched_flow = reverse_edge.capacity
        if matched_flow <= 0:
            continue

        matched_qty = _flow_int_to_decimal(matched_flow)
        lot = lot_candidates[lot_index]
        sell_tx = sells[sell_index].transaction
        time_test_passed = is_time_test_passed(lot.buy_date, sell_tx.date)
        sell_price = _ensure_transaction_has_price(sell_tx)
        total_pl = (sell_price - lot.price) * matched_qty
        taxable_pl = Decimal("0") if time_test_passed else total_pl

        matches_by_sell_index[sell_index].append(
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

    sell_matches: List[SellMatch] = []
    for sell_index, sell in enumerate(sells):
        sell_tx = sell.transaction
        matches = sorted(
            matches_by_sell_index.get(sell_index, []),
            key=lambda match: (0 if match.time_test_passed else 1, -match.sell_price + match.buy_price, match.buy_date, match.buy_source_file.lower(), match.buy_row_number),
        )
        matched_total = sum((match.matched_qty for match in matches), Decimal("0"))
        if sell_tx.quantity - matched_total > QUANTITY_TOLERANCE:
            raise ValueError(
                f"{ticker}: TIME_TEST_MAX could not fully match SELL {sell_tx.source_file}:{sell_tx.original_row_number} "
                f"on {sell_tx.date.isoformat()}"
            )

        total_pl = sum((match.total_pl for match in matches), Decimal("0"))
        total_taxable_pl = sum((match.taxable_pl for match in matches), Decimal("0"))
        sell_matches.append(
            SellMatch(
                sell_date=sell_tx.date,
                sell_quantity=sell_tx.quantity,
                sell_price=_ensure_transaction_has_price(sell_tx),
                sell_source_file=sell_tx.source_file,
                sell_row_number=sell_tx.original_row_number,
                method="time_test_max",
                matches=matches,
                total_pl=total_pl,
                total_taxable_pl=total_taxable_pl,
            )
        )

    next_remaining_lots = [lot for lot in lot_candidates if lot.quantity > 0 and not _is_within_quantity_tolerance(lot.quantity)]
    return sell_matches, next_remaining_lots


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


OPEN_POSITIONS_COL_WIDTHS = [120, 80]
YEAR_HISTORY_COL_WIDTHS = [102, 38, 46, 40, 86, 70, 82, 84]


def _format_holding_period(days: int) -> str:
    return f"{days} d"


def _format_match_status(time_test_passed: bool, holding_period_days: int) -> str:
    return f"{'PASS' if time_test_passed else 'FAIL'} | {_format_holding_period(holding_period_days)}"


def _compute_year_summary(
    analysis: TickerAnalysis,
    year: int,
    current_year: int,
    fx_rate_book: FxRateBook,
) -> YearSummary:
    year_sells = [tx for tx in analysis.transactions if tx.date.year == year and tx.action == "SELL"]
    total_income = sum(((_compute_trade_value(tx.quantity, tx.price) or Decimal("0")) for tx in year_sells), Decimal("0"))

    if year >= current_year:
        return YearSummary(
            total_income=total_income,
            total_income_czk=None,
            total_pl=None,
            total_pl_czk=None,
            taxable_pl=None,
            taxable_pl_czk=None,
            over_three_year_pl=None,
            over_three_year_pl_czk=None,
        )

    total_income_czk = sum(
        ((_compute_trade_value_czk(tx.quantity, tx.price, tx.date, fx_rate_book) or Decimal("0")) for tx in year_sells),
        Decimal("0"),
    )

    sell_matches = analysis.sell_matches_by_year.get(year, [])
    total_pl = sum((sell_match.total_pl for sell_match in sell_matches), Decimal("0"))
    taxable_pl = sum((sell_match.total_taxable_pl for sell_match in sell_matches), Decimal("0"))
    total_pl_czk = sum(
        (_compute_match_pl_czk(match, sell_match.sell_date, fx_rate_book) for sell_match in sell_matches for match in sell_match.matches),
        Decimal("0"),
    )
    over_three_year_pl = sum(
        (match.total_pl for sell_match in sell_matches for match in sell_match.matches if match.time_test_passed),
        Decimal("0"),
    )
    over_three_year_pl_czk = sum(
        (
            _compute_match_pl_czk(match, sell_match.sell_date, fx_rate_book)
            for sell_match in sell_matches
            for match in sell_match.matches
            if match.time_test_passed
        ),
        Decimal("0"),
    )
    return YearSummary(
        total_income=total_income,
        total_income_czk=total_income_czk,
        total_pl=total_pl,
        total_pl_czk=total_pl_czk,
        taxable_pl=taxable_pl,
        taxable_pl_czk=total_pl_czk - over_three_year_pl_czk,
        over_three_year_pl=over_three_year_pl,
        over_three_year_pl_czk=over_three_year_pl_czk,
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


def _sum_optional_decimals(values: List[Optional[Decimal]]) -> Optional[Decimal]:
    present_values = [value for value in values if value is not None]
    if not present_values:
        return None
    return sum(present_values, Decimal("0"))


def _compute_aggregate_year_summaries(
    analyses: List[TickerAnalysis],
    current_year: int,
    fx_rate_book: FxRateBook,
) -> Dict[int, YearSummary]:
    years = sorted({year for analysis in analyses for year in analysis.years}, reverse=True)
    aggregated: Dict[int, YearSummary] = {}

    for year in years:
        summaries = [
            _compute_year_summary(analysis, year, current_year, fx_rate_book)
            for analysis in analyses
            if year in analysis.years
        ]
        aggregated[year] = YearSummary(
            total_income=sum((summary.total_income for summary in summaries), Decimal("0")),
            total_income_czk=_sum_optional_decimals([summary.total_income_czk for summary in summaries]),
            total_pl=_sum_optional_decimals([summary.total_pl for summary in summaries]),
            total_pl_czk=_sum_optional_decimals([summary.total_pl_czk for summary in summaries]),
            taxable_pl=_sum_optional_decimals([summary.taxable_pl for summary in summaries]),
            taxable_pl_czk=_sum_optional_decimals([summary.taxable_pl_czk for summary in summaries]),
            over_three_year_pl=_sum_optional_decimals([summary.over_three_year_pl for summary in summaries]),
            over_three_year_pl_czk=_sum_optional_decimals([summary.over_three_year_pl_czk for summary in summaries]),
        )

    return aggregated


def build_all_tickers_year_summary_pdf(
    analyses: List[TickerAnalysis],
    output_dir: Path,
    generated_at: datetime,
    current_year: int,
    fx_rate_book: FxRateBook,
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

    aggregated = _compute_aggregate_year_summaries(analyses, current_year, fx_rate_book)
    rows = [[
        "Year",
        "FX",
        "Income USD/CZK",
        "Profit/Loss USD/CZK",
        "3 years rule PASS USD/CZK",
        "3 years rule FAIL USD/CZK",
    ]]

    for year in sorted(aggregated, reverse=True):
        summary = aggregated[year]
        rows.append([
            str(year),
            _year_fx_label(year, current_year, fx_rate_book),
            _fmt_usd_czk_pair(summary.total_income, summary.total_income_czk),
            _fmt_usd_czk_pair(summary.total_pl, summary.total_pl_czk),
            _fmt_usd_czk_pair(summary.over_three_year_pl, summary.over_three_year_pl_czk),
            _fmt_usd_czk_pair(summary.taxable_pl, summary.taxable_pl_czk),
        ])

    table = Table(rows, repeatRows=1, colWidths=[46, 48, 102, 102, 112, 112], hAlign="LEFT")
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
            f"All Tickers Year Summary | FX mode: {fx_rate_book.mode} | Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
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

        story.append(_build_year_history_table(analysis, year, current_year, fx_rate_book, exported_styles))
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


def write_summary(output_dir: Path, analyses: List[TickerAnalysis], fx_rate_book: FxRateBook) -> Path:
    summary_path = output_dir / "_export_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ticker",
                "pdf_file",
                "fx_mode",
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
                    fx_rate_book.mode,
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

    try:
        fx_rate_book = load_fx_rate_book(config.fx_config)
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
        created_pdfs.append(build_pdf_for_ticker(analysis, args.output_dir, generated_at, config.current_year, fx_rate_book))
    all_tickers_summary_pdf = build_all_tickers_year_summary_pdf(
        analyses,
        args.output_dir,
        generated_at,
        config.current_year,
        fx_rate_book,
    )

    summary_path = write_summary(args.output_dir, analyses, fx_rate_book)
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
