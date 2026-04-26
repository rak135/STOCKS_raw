from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest


@pytest.mark.integration
def test_cross_source_matching_is_global_per_ticker(tax_module, tmp_path, csv_writer):
    input_dir = tmp_path / "csv"
    csv_writer(
        input_dir / "broker_a_portfolio_new.csv",
        [
            {
                "Symbol": "PLTR",
                "Trade Date": "20210104",
                "Purchase Price": "10",
                "Quantity": "5",
                "Transaction Type": "BUY",
            }
        ],
    )
    csv_writer(
        input_dir / "broker_b_portfolio_new.csv",
        [
            {
                "Symbol": "PLTR",
                "Trade Date": "20250210",
                "Purchase Price": "50",
                "Quantity": "5",
                "Transaction Type": "SELL",
            }
        ],
    )

    transactions = []
    for csv_file in tax_module.discover_csv_files(input_dir):
        transactions.extend(tax_module.extract_transactions_from_file(csv_file).transactions)

    grouped = tax_module.group_by_ticker(transactions)
    analysis = tax_module.analyze_ticker(
        "PLTR",
        grouped["PLTR"],
        tax_module.TaxConfig(current_year=2026, methods_by_ticker={"PLTR": {2021: "fifo", 2025: "fifo"}}),
    )

    sell_match = analysis.sell_matches_by_year[2025][0]
    assert sell_match.matches[0].buy_source_file == "broker_a_portfolio_new.csv"
    assert analysis.open_quantity == Decimal("0")


@pytest.mark.integration
def test_aggregate_year_summary_sums_all_tickers(tax_module, tx_factory):
    alpha = tax_module.analyze_ticker(
        "AAA",
        [
            tx_factory(ticker="AAA", action="BUY", when=date(2021, 1, 1), quantity="1", price="10", source_file="a.csv"),
            tx_factory(ticker="AAA", action="SELL", when=date(2025, 1, 1), quantity="1", price="50", source_file="a.csv", row_number=3),
        ],
        tax_module.TaxConfig(current_year=2026, methods_by_ticker={"AAA": {2021: "fifo", 2025: "fifo"}}),
    )
    beta = tax_module.analyze_ticker(
        "BBB",
        [
            tx_factory(ticker="BBB", action="BUY", when=date(2024, 1, 1), quantity="1", price="30", source_file="b.csv"),
            tx_factory(ticker="BBB", action="SELL", when=date(2025, 1, 2), quantity="1", price="20", source_file="b.csv", row_number=3),
        ],
        tax_module.TaxConfig(current_year=2026, methods_by_ticker={"BBB": {2024: "fifo", 2025: "fifo"}}),
    )

    fx_rate_book = tax_module.load_fx_rate_book(
        tax_module.FxConfig(mode="annual", annual_rates={2021: Decimal("20"), 2024: Decimal("22"), 2025: Decimal("25")})
    )

    summaries = tax_module._compute_aggregate_year_summaries([alpha, beta], 2026, fx_rate_book)

    assert summaries[2025].total_income == Decimal("70")
    assert summaries[2025].total_income_czk == Decimal("1750")
    assert summaries[2025].total_pl == Decimal("30")
    assert summaries[2025].total_pl_czk == Decimal("890")
    assert summaries[2025].taxable_pl == Decimal("-10")
    assert summaries[2025].taxable_pl_czk == Decimal("-160")
    assert summaries[2025].over_three_year_pl == Decimal("40")
    assert summaries[2025].over_three_year_pl_czk == Decimal("1050")
