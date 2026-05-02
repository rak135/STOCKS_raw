from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stock_tax_report.analysis.ticker_analysis import analyze_ticker
from stock_tax_report.domain.config import TaxConfig
from stock_tax_report.matching.common import is_time_test_passed


@pytest.mark.functional
def test_time_test_passed_at_exactly_three_years_plus_one_day():
    buy = date(2022, 5, 1)
    assert not is_time_test_passed(buy, date(2025, 5, 1))      # exactly 3y -> FAIL
    assert is_time_test_passed(buy, date(2025, 5, 2))          # 3y + 1d -> PASS


@pytest.mark.functional
def test_time_test_passed_handles_leap_day_boundary():
    buy = date(2020, 2, 29)
    # 3 years from leap day -> 2023-02-28 in our domain
    assert not is_time_test_passed(buy, date(2023, 2, 28))
    assert is_time_test_passed(buy, date(2023, 3, 1))


@pytest.mark.functional
def test_time_test_max_leaves_residual_lots_open(tx_factory):
    transactions = [
        tx_factory(action="BUY", when=date(2021, 1, 1), quantity="5", price="10", source_file="pass.csv"),
        tx_factory(action="BUY", when=date(2024, 1, 1), quantity="5", price="20", source_file="fail.csv", row_number=3),
        tx_factory(action="SELL", when=date(2025, 6, 1), quantity="3", price="50", source_file="sell.csv", row_number=4),
    ]
    config = TaxConfig(current_year=2026, methods_by_ticker={"TEST": {2021: "fifo", 2024: "fifo", 2025: "time_test_max"}})
    analysis = analyze_ticker("TEST", transactions, config)

    # 3 sold, 5 + 5 - 3 = 7 remaining open
    assert analysis.open_quantity == Decimal("7")


@pytest.mark.functional
def test_time_test_max_mixes_pass_and_fail_in_one_sell(tx_factory):
    # 5 pass + 5 fail; sell 7 -> 5 pass + 2 fail allocated
    transactions = [
        tx_factory(action="BUY", when=date(2021, 1, 1), quantity="5", price="10", source_file="pass.csv"),
        tx_factory(action="BUY", when=date(2024, 1, 1), quantity="5", price="20", source_file="fail.csv", row_number=3),
        tx_factory(action="SELL", when=date(2025, 6, 1), quantity="7", price="50", source_file="sell.csv", row_number=4),
    ]
    config = TaxConfig(current_year=2026, methods_by_ticker={"TEST": {2021: "fifo", 2024: "fifo", 2025: "time_test_max"}})
    analysis = analyze_ticker("TEST", transactions, config)

    sell_match = analysis.sell_matches_by_year[2025][0]
    pass_qty = sum((m.matched_qty for m in sell_match.matches if m.time_test_passed), Decimal("0"))
    fail_qty = sum((m.matched_qty for m in sell_match.matches if not m.time_test_passed), Decimal("0"))
    assert pass_qty == Decimal("5")
    assert fail_qty == Decimal("2")


@pytest.mark.functional
def test_time_test_max_when_no_pass_lots_falls_back_to_remaining(tx_factory):
    # All buys within 3 years -> none pass, all fail
    transactions = [
        tx_factory(action="BUY", when=date(2024, 1, 1), quantity="5", price="20", source_file="fail.csv"),
        tx_factory(action="SELL", when=date(2025, 6, 1), quantity="3", price="50", source_file="sell.csv", row_number=3),
    ]
    config = TaxConfig(current_year=2026, methods_by_ticker={"TEST": {2024: "fifo", 2025: "time_test_max"}})
    analysis = analyze_ticker("TEST", transactions, config)

    sell_match = analysis.sell_matches_by_year[2025][0]
    assert all(not m.time_test_passed for m in sell_match.matches)
    assert sell_match.total_taxable_pl == Decimal("90")  # (50-20)*3
