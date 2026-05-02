from __future__ import annotations

import pytest

from stock_tax_report.cli import main as cli_main


@pytest.mark.end_to_end
def test_main_generates_all_expected_export_artifacts(tmp_path, csv_writer):
    input_dir = tmp_path / "csv"
    output_dir = tmp_path / "out"
    bundle_root = tmp_path / "bundles"
    tax_methods_file = tmp_path / "tax_methods.toml"

    csv_writer(
        input_dir / "alpha_portfolio_new.csv",
        [
            {"Symbol": "PLTR", "Trade Date": "20210510", "Purchase Price": "18.76", "Quantity": "10", "Transaction Type": "BUY"},
            {"Symbol": "PLTR", "Trade Date": "20231129", "Purchase Price": "20.01", "Quantity": "10", "Transaction Type": "BUY"},
            {"Symbol": "PLTR", "Trade Date": "20250929", "Purchase Price": "180.00", "Quantity": "10", "Transaction Type": "SELL"},
            {"Symbol": "PLTR", "Trade Date": "20260115", "Purchase Price": "190.00", "Quantity": "1", "Transaction Type": "SELL"},
        ],
    )
    tax_methods_file.write_text(
        'current_year = 2026\n'
        '\n'
        '[fx_mode_by_year]\n'
        '2021 = "annual"\n'
        '2023 = "annual"\n'
        '2025 = "annual"\n'
        '\n'
        '[fx_annual_rates]\n'
        '2021 = 21\n'
        '2023 = 22\n'
        '2025 = 24\n'
        '\n'
        '[PLTR]\n'
        '2021 = "FIFO"\n'
        '2023 = "FIFO"\n'
        '2025 = "TIME_TEST_MAX"\n',
        encoding="utf-8",
    )

    rc = cli_main([
        "--input-dir", str(input_dir),
        "--output-dir", str(output_dir),
        "--tax-methods-file", str(tax_methods_file),
        "--bundle-root", str(bundle_root),
    ])

    assert rc == 0
    assert (output_dir / "PLTR.pdf").exists()
    assert (output_dir / "_all_tickers_year_summary.pdf").exists()
    assert (output_dir / "_export_summary.csv").exists()
    assert (output_dir / "_export_warnings.txt").exists()
    assert (bundle_root / "tax_2026" / "05_outputs" / "PLTR.pdf").exists()
    assert (bundle_root / "tax_2026" / "bundle.json").exists()


@pytest.mark.end_to_end
def test_write_template_creates_tax_methods_stub(tmp_path, csv_writer):
    input_dir = tmp_path / "csv"
    tax_methods_file = tmp_path / "tax_methods.toml"

    csv_writer(
        input_dir / "alpha_portfolio_new.csv",
        [
            {"Symbol": "NKE", "Trade Date": "20240110", "Purchase Price": "30", "Quantity": "2", "Transaction Type": "BUY"},
            {"Symbol": "NKE", "Trade Date": "20250210", "Purchase Price": "50", "Quantity": "2", "Transaction Type": "SELL"},
        ],
    )

    rc = cli_main([
        "--input-dir", str(input_dir),
        "--tax-methods-file", str(tax_methods_file),
        "--write-template",
    ])

    assert rc == 0
    text = tax_methods_file.read_text(encoding="utf-8")
    assert "current_year = 2025" in text
    assert "[fx_mode_by_year]" in text
    assert "[fx_annual_rates]" in text
    assert "[NKE]" in text
