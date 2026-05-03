from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stock_tax_report.analysis.ticker_analysis import analyze_ticker
from stock_tax_report.analysis.year_summary import (
    _compute_aggregate_year_summaries,
    _compute_year_summary,
    _sum_optional_decimals,
)
from stock_tax_report.domain.config import TaxConfig
from stock_tax_report.domain.fx import FxConfig
from stock_tax_report.io.fx_loader import load_fx_rate_book


def _annual_book(rates):
    return load_fx_rate_book(FxConfig(
        mode_by_year={year: "annual" for year in rates},
        annual_rates=rates,
    ))


@pytest.mark.unit
def test_sum_optional_decimals_returns_none_for_all_none():
    assert _sum_optional_decimals([None, None]) is None
    assert _sum_optional_decimals([]) is None
    assert _sum_optional_decimals([None, Decimal("1"), Decimal("2")]) == Decimal("3")


@pytest.mark.unit
def test_year_summary_skips_pl_for_current_year(tx_factory):
    txs = [
        tx_factory(action="BUY", when=date(2024, 1, 1), price="10"),
        tx_factory(action="SELL", when=date(2026, 1, 1), price="20", row_number=3),
    ]
    config = TaxConfig(current_year=2026, methods_by_ticker={"TEST": {2024: "fifo"}})
    analysis = analyze_ticker("TEST", txs, config)

    book = _annual_book({2024: Decimal("23"), 2025: Decimal("24")})
    summary = _compute_year_summary(analysis, year=2026, current_year=2026, fx_rate_book=book)

    assert summary.total_income == Decimal("20")
    assert summary.total_income_czk is None
    assert summary.total_pl is None
    assert summary.taxable_pl is None
    assert summary.fail_income is None
    assert summary.fail_costs is None
    assert summary.over_three_year_pl is None


@pytest.mark.unit
def test_year_summary_separates_time_test_pass_pl(tx_factory):
    txs = [
        tx_factory(action="BUY", when=date(2021, 1, 1), price="10"),
        tx_factory(action="BUY", when=date(2024, 1, 1), price="40", row_number=3),
        tx_factory(action="SELL", when=date(2025, 6, 1), quantity="2", price="50", row_number=4),
    ]
    config = TaxConfig(current_year=2026, methods_by_ticker={"TEST": {2021: "fifo", 2024: "fifo", 2025: "fifo"}})
    analysis = analyze_ticker("TEST", txs, config)
    book = _annual_book({2021: Decimal("20"), 2024: Decimal("23"), 2025: Decimal("25")})

    summary = _compute_year_summary(analysis, year=2025, current_year=2026, fx_rate_book=book)

    # Total P/L: (50-10) + (50-40) = 50
    assert summary.total_pl == Decimal("50")
    # Pass: only 2021 lot (>3y) -> 50-10 = 40
    assert summary.over_three_year_pl == Decimal("40")
    # Taxable: total - pass = 10
    assert summary.taxable_pl == Decimal("10")
    # FAIL lot only: sold for 50, bought for 40.
    assert summary.fail_income == Decimal("50")
    assert summary.fail_income_czk == Decimal("1250")
    assert summary.fail_costs == Decimal("40")
    assert summary.fail_costs_czk == Decimal("920")


@pytest.mark.unit
def test_aggregate_year_summaries_aggregates_only_present_years(tx_factory):
    a = analyze_ticker(
        "AAA",
        [
            tx_factory(ticker="AAA", action="BUY", when=date(2024, 1, 1), price="10", source_file="a.csv"),
            tx_factory(ticker="AAA", action="SELL", when=date(2025, 1, 1), price="30", source_file="a.csv", row_number=3),
        ],
        TaxConfig(current_year=2026, methods_by_ticker={"AAA": {2024: "fifo", 2025: "fifo"}}),
    )
    b = analyze_ticker(
        "BBB",
        [
            tx_factory(ticker="BBB", action="BUY", when=date(2023, 1, 1), price="5", source_file="b.csv"),
            tx_factory(ticker="BBB", action="SELL", when=date(2024, 1, 1), price="15", source_file="b.csv", row_number=3),
        ],
        TaxConfig(current_year=2026, methods_by_ticker={"BBB": {2023: "fifo", 2024: "fifo"}}),
    )
    book = _annual_book({2023: Decimal("22"), 2024: Decimal("23"), 2025: Decimal("25")})

    summaries = _compute_aggregate_year_summaries([a, b], 2026, book)

    # AAA contributes to 2025; BBB to 2024
    assert summaries[2025].total_income == Decimal("30")
    assert summaries[2024].total_income == Decimal("15")
