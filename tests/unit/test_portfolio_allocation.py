from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from stock_tax_report.analysis.portfolio_allocation import (
    build_portfolio_allocation,
    compute_current_positions,
)
from stock_tax_report.analysis.ticker_analysis import analyze_ticker
from stock_tax_report.domain.config import TaxConfig
from stock_tax_report.domain.portfolio import MarketPrice, MarketPriceSnapshot, PortfolioPosition


@pytest.mark.unit
def test_compute_current_positions_includes_current_year_sells(tx_factory):
    analysis = analyze_ticker(
        "AAA",
        [
            tx_factory(ticker="AAA", action="BUY", when=date(2024, 1, 1), quantity="10", price="10"),
            tx_factory(ticker="AAA", action="SELL", when=date(2026, 2, 1), quantity="3", price="20", row_number=3),
        ],
        TaxConfig(current_year=2026, methods_by_ticker={"AAA": {2024: "fifo"}}),
    )

    positions = compute_current_positions([analysis])

    assert len(positions) == 1
    assert positions[0].ticker == "AAA"
    assert positions[0].quantity == Decimal("7")


@pytest.mark.unit
def test_build_portfolio_allocation_calculates_market_value_percentages():
    fetched_at = datetime(2026, 5, 8, 12, 0, 0)
    snapshot = MarketPriceSnapshot(
        provider="test",
        fetched_at=fetched_at,
        prices=[
            MarketPrice("AAA", Decimal("10"), "test", fetched_at),
            MarketPrice("BBB", Decimal("30"), "test", fetched_at),
        ],
        errors=[],
    )
    allocation = build_portfolio_allocation(
        [
            PortfolioPosition("AAA", Decimal("2")),
            PortfolioPosition("BBB", Decimal("1")),
        ],
        snapshot,
    )

    assert allocation.total_value_usd == Decimal("50")
    assert [item.ticker for item in allocation.items] == ["BBB", "AAA"]
    assert allocation.items[0].allocation_percent == Decimal("60.0")
    assert allocation.items[1].allocation_percent == Decimal("40.0")
