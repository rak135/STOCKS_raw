from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest


@pytest.mark.unit
def test_fifo_matching_uses_oldest_buy_first(tax_module, tx_factory):
    lots = [
        tax_module.BuyLot("a.csv", "TEST", date(2023, 1, 1), Decimal("2"), Decimal("10"), 2),
        tax_module.BuyLot("b.csv", "TEST", date(2023, 2, 1), Decimal("2"), Decimal("20"), 3),
    ]
    sell = tx_factory(action="SELL", when=date(2025, 1, 1), quantity="3", price="30", row_number=4)

    match = tax_module.match_sell_transaction(lots, sell, "fifo")

    assert [item.buy_date for item in match.matches] == [date(2023, 1, 1), date(2023, 2, 1)]
    assert [item.matched_qty for item in match.matches] == [Decimal("2"), Decimal("1")]


@pytest.mark.unit
def test_lifo_matching_uses_newest_buy_first(tax_module, tx_factory):
    lots = [
        tax_module.BuyLot("a.csv", "TEST", date(2023, 1, 1), Decimal("2"), Decimal("10"), 2),
        tax_module.BuyLot("b.csv", "TEST", date(2023, 2, 1), Decimal("2"), Decimal("20"), 3),
    ]
    sell = tx_factory(action="SELL", when=date(2025, 1, 1), quantity="3", price="30", row_number=4)

    match = tax_module.match_sell_transaction(lots, sell, "lifo")

    assert [item.buy_date for item in match.matches] == [date(2023, 2, 1), date(2023, 1, 1)]
    assert [item.matched_qty for item in match.matches] == [Decimal("2"), Decimal("1")]


@pytest.mark.unit
def test_min_gains_prefers_highest_cost_basis(tax_module, tx_factory):
    lots = [
        tax_module.BuyLot("cheap.csv", "TEST", date(2023, 1, 1), Decimal("2"), Decimal("10"), 2),
        tax_module.BuyLot("expensive.csv", "TEST", date(2023, 2, 1), Decimal("2"), Decimal("28"), 3),
    ]
    sell = tx_factory(action="SELL", when=date(2025, 1, 1), quantity="2", price="30", row_number=4)

    match = tax_module.match_sell_transaction(lots, sell, "min_gains")

    assert match.matches[0].buy_price == Decimal("28")
    assert match.total_taxable_pl == Decimal("4")


@pytest.mark.unit
def test_max_gains_prefers_lowest_cost_basis(tax_module, tx_factory):
    lots = [
        tax_module.BuyLot("cheap.csv", "TEST", date(2023, 1, 1), Decimal("2"), Decimal("10"), 2),
        tax_module.BuyLot("expensive.csv", "TEST", date(2023, 2, 1), Decimal("2"), Decimal("28"), 3),
    ]
    sell = tx_factory(action="SELL", when=date(2025, 1, 1), quantity="2", price="30", row_number=4)

    match = tax_module.match_sell_transaction(lots, sell, "max_gains")

    assert match.matches[0].buy_price == Decimal("10")
    assert match.total_taxable_pl == Decimal("40")
