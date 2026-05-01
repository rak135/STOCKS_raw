from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List

from stock_tax_report.domain.lots import BuyLot
from stock_tax_report.domain.matches import MatchDetail, SellMatch
from stock_tax_report.domain.transactions import Transaction
from stock_tax_report.matching.common import (
    QUANTITY_TOLERANCE,
    _copy_buy_lot,
    _create_buy_lot_from_transaction,
    _ensure_transaction_has_price,
    _fmt_decimal,
    _holding_period_days,
    _is_within_quantity_tolerance,
    _lot_taxable_unit_pl,
    _lot_total_unit_pl,
    is_time_test_passed,
)


FLOW_SCALE = Decimal("100000")


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


def _decimal_to_flow_int(value: Decimal) -> int:
    return int((value * FLOW_SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def _flow_int_to_decimal(value: int) -> Decimal:
    return Decimal(value) / FLOW_SCALE


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
