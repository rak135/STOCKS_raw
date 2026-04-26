from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest


@pytest.mark.functional
def test_time_test_max_assigns_pass_lots_to_highest_2025_sell_prices(tax_module, tx_factory):
    transactions = [
        tx_factory(action="BUY", when=date(2021, 1, 1), quantity="5", price="10", source_file="pass.csv", row_number=2),
        tx_factory(action="BUY", when=date(2021, 1, 2), quantity="5", price="20", source_file="pass.csv", row_number=3),
        tx_factory(action="BUY", when=date(2024, 1, 1), quantity="10", price="90", source_file="fail.csv", row_number=2),
        tx_factory(action="SELL", when=date(2025, 2, 1), quantity="10", price="100", source_file="sell.csv", row_number=10),
        tx_factory(action="SELL", when=date(2025, 9, 1), quantity="10", price="200", source_file="sell.csv", row_number=11),
    ]
    config = tax_module.TaxConfig(current_year=2026, methods_by_ticker={"TEST": {2021: "fifo", 2024: "fifo", 2025: "time_test_max"}})

    analysis = tax_module.analyze_ticker("TEST", transactions, config)
    sell_matches = analysis.sell_matches_by_year[2025]
    feb_sell = next(match for match in sell_matches if match.sell_date == date(2025, 2, 1))
    sep_sell = next(match for match in sell_matches if match.sell_date == date(2025, 9, 1))

    assert sum((item.total_pl for item in feb_sell.matches if item.time_test_passed), Decimal("0")) == Decimal("0")
    assert sum((item.total_pl for item in sep_sell.matches if item.time_test_passed), Decimal("0")) == Decimal("1850")
    assert feb_sell.total_taxable_pl == Decimal("100")
    assert sep_sell.total_taxable_pl == Decimal("0")


@pytest.mark.functional
def test_time_test_max_increases_pass_pl_for_pltr_like_scenario(tax_module, tx_factory):
    transactions = [
        tx_factory(action="BUY", when=date(2021, 5, 10), quantity="10", price="18.76", source_file="pass.csv", row_number=2),
        tx_factory(action="BUY", when=date(2021, 4, 19), quantity="2", price="21.68", source_file="pass.csv", row_number=3),
        tx_factory(action="BUY", when=date(2021, 4, 19), quantity="4", price="21.75", source_file="pass.csv", row_number=4),
        tx_factory(action="BUY", when=date(2021, 4, 13), quantity="1", price="24.05", source_file="pass.csv", row_number=5),
        tx_factory(action="BUY", when=date(2023, 11, 29), quantity="20", price="20.01", source_file="fail.csv", row_number=6),
        tx_factory(action="SELL", when=date(2025, 2, 10), quantity="10", price="114.00", source_file="sell.csv", row_number=10),
        tx_factory(action="SELL", when=date(2025, 9, 29), quantity="17", price="180.00", source_file="sell.csv", row_number=11),
    ]
    fifo_analysis = tax_module.analyze_ticker(
        "TEST",
        transactions,
        tax_module.TaxConfig(current_year=2026, methods_by_ticker={"TEST": {2021: "fifo", 2023: "fifo", 2025: "fifo"}}),
    )
    tt_analysis = tax_module.analyze_ticker(
        "TEST",
        transactions,
        tax_module.TaxConfig(current_year=2026, methods_by_ticker={"TEST": {2021: "fifo", 2023: "fifo", 2025: "time_test_max"}}),
    )

    fifo_pass = sum((item.total_pl for match in fifo_analysis.sell_matches_by_year[2025] for item in match.matches if item.time_test_passed), Decimal("0"))
    tt_pass = sum((item.total_pl for match in tt_analysis.sell_matches_by_year[2025] for item in match.matches if item.time_test_passed), Decimal("0"))
    fifo_fail = sum((match.total_taxable_pl for match in fifo_analysis.sell_matches_by_year[2025]), Decimal("0"))
    tt_fail = sum((match.total_taxable_pl for match in tt_analysis.sell_matches_by_year[2025]), Decimal("0"))

    assert tt_pass > fifo_pass
    assert tt_fail < fifo_fail
