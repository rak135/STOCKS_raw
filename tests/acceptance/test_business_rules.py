from __future__ import annotations

from datetime import date

import pytest

from stock_tax_report.analysis.ticker_analysis import analyze_ticker
from stock_tax_report.cli import main as cli_main
from stock_tax_report.domain.config import TaxConfig


@pytest.mark.acceptance
def test_export_fails_when_tax_method_missing_for_required_year(tmp_path, csv_writer):
    input_dir = tmp_path / "csv"
    output_dir = tmp_path / "out"
    tax_methods_file = tmp_path / "tax_methods.toml"

    csv_writer(
        input_dir / "alpha_portfolio_new.csv",
        [
            {"Symbol": "NKE", "Trade Date": "20240110", "Purchase Price": "30", "Quantity": "2", "Transaction Type": "BUY"},
            {"Symbol": "NKE", "Trade Date": "20250210", "Purchase Price": "50", "Quantity": "2", "Transaction Type": "SELL"},
        ],
    )
    tax_methods_file.write_text(
        'current_year = 2026\n'
        '\n'
        '[fx_mode_by_year]\n'
        '2024 = "annual"\n'
        '2025 = "annual"\n'
        '\n'
        '[fx_annual_rates]\n'
        '2024 = 23\n'
        '2025 = 25\n'
        '\n'
        '[NKE]\n'
        '2024 = "FIFO"\n',
        encoding="utf-8",
    )

    rc = cli_main([
        "--input-dir", str(input_dir),
        "--output-dir", str(output_dir),
        "--tax-methods-file", str(tax_methods_file),
        "--no-bundle",
    ])
    assert rc == 2


@pytest.mark.acceptance
def test_analysis_fails_when_sell_exceeds_buy_quantity(tx_factory):
    transactions = [
        tx_factory(action="BUY", when=date(2024, 1, 1), quantity="1", price="10"),
        tx_factory(action="SELL", when=date(2025, 1, 1), quantity="2", price="20", row_number=3),
    ]
    config = TaxConfig(current_year=2026, methods_by_ticker={"TEST": {2024: "fifo", 2025: "fifo"}})

    with pytest.raises(ValueError, match="exceeds available BUY lots"):
        analyze_ticker("TEST", transactions, config)
