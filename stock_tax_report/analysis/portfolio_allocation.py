from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, List

from stock_tax_report.domain.analysis import TickerAnalysis
from stock_tax_report.domain.portfolio import (
    MarketPrice,
    MarketPriceSnapshot,
    PortfolioAllocationItem,
    PortfolioAllocationResult,
    PortfolioPosition,
)
from stock_tax_report.matching.common import _is_within_quantity_tolerance


def compute_current_positions(analyses: Iterable[TickerAnalysis]) -> List[PortfolioPosition]:
    positions: List[PortfolioPosition] = []

    for analysis in analyses:
        quantity = Decimal("0")
        for tx in analysis.transactions:
            if tx.action == "BUY":
                quantity += tx.quantity
            elif tx.action == "SELL":
                quantity -= tx.quantity

        if _is_within_quantity_tolerance(quantity):
            quantity = Decimal("0")
        if quantity > 0:
            positions.append(PortfolioPosition(ticker=analysis.ticker, quantity=quantity))

    return sorted(positions, key=lambda item: item.ticker)


def build_portfolio_allocation(
    positions: Iterable[PortfolioPosition],
    price_snapshot: MarketPriceSnapshot,
) -> PortfolioAllocationResult:
    prices_by_ticker: Dict[str, MarketPrice] = {
        price.ticker: price for price in price_snapshot.prices
    }
    warnings = list(price_snapshot.errors)
    raw_items: List[tuple[PortfolioPosition, MarketPrice, Decimal]] = []

    for position in positions:
        price = prices_by_ticker.get(position.ticker)
        if price is None:
            warnings.append(f"{position.ticker}: missing market price")
            continue

        value_usd = position.quantity * price.price_usd
        if value_usd <= 0:
            continue
        raw_items.append((position, price, value_usd))

    total_value = sum((item[2] for item in raw_items), Decimal("0"))
    if total_value <= 0:
        return PortfolioAllocationResult(
            items=[],
            total_value_usd=Decimal("0"),
            price_snapshot=price_snapshot,
            warnings=warnings,
        )

    items = [
        PortfolioAllocationItem(
            ticker=position.ticker,
            quantity=position.quantity,
            price_usd=price.price_usd,
            value_usd=value_usd,
            allocation_percent=(value_usd / total_value) * Decimal("100"),
        )
        for position, price, value_usd in raw_items
    ]
    items.sort(key=lambda item: (-item.value_usd, item.ticker))

    return PortfolioAllocationResult(
        items=items,
        total_value_usd=total_value,
        price_snapshot=price_snapshot,
        warnings=warnings,
    )
