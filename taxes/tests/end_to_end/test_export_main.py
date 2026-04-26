from __future__ import annotations

import sys

import pytest


@pytest.mark.end_to_end
def test_main_generates_all_expected_export_artifacts(tax_module, tmp_path, csv_writer, monkeypatch):
    input_dir = tmp_path / "csv"
    output_dir = tmp_path / "out"
    tax_methods_file = tmp_path / "tax_methods.toml"

    csv_writer(
        input_dir / "alpha_portfolio_new.csv",
        [
            {"Symbol": "PLTR", "Trade Date": "20210510", "Purchase Price": "18.76", "Quantity": "10", "Transaction Type": "BUY"},
            {"Symbol": "PLTR", "Trade Date": "20231129", "Purchase Price": "20.01", "Quantity": "10", "Transaction Type": "BUY"},
            {"Symbol": "PLTR", "Trade Date": "20250929", "Purchase Price": "180.00", "Quantity": "10", "Transaction Type": "SELL"},
        ],
    )
    tax_methods_file.write_text(
        'current_year = 2026\n\n[PLTR]\n2021 = "FIFO"\n2023 = "FIFO"\n2025 = "TIME_TEST_MAX"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_ticker_tax_method_pdfs.py",
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--tax-methods-file",
            str(tax_methods_file),
        ],
    )

    result = tax_module.main()

    assert result == 0
    assert (output_dir / "PLTR.pdf").exists()
    assert (output_dir / "_all_tickers_year_summary.pdf").exists()
    assert (output_dir / "_export_summary.csv").exists()
    assert (output_dir / "_export_warnings.txt").exists()


@pytest.mark.end_to_end
def test_write_template_creates_tax_methods_stub(tax_module, tmp_path, csv_writer, monkeypatch):
    input_dir = tmp_path / "csv"
    tax_methods_file = tmp_path / "tax_methods.toml"

    csv_writer(
        input_dir / "alpha_portfolio_new.csv",
        [
            {"Symbol": "NKE", "Trade Date": "20240110", "Purchase Price": "30", "Quantity": "2", "Transaction Type": "BUY"},
            {"Symbol": "NKE", "Trade Date": "20250210", "Purchase Price": "50", "Quantity": "2", "Transaction Type": "SELL"},
        ],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_ticker_tax_method_pdfs.py",
            "--input-dir",
            str(input_dir),
            "--tax-methods-file",
            str(tax_methods_file),
            "--write-template",
        ],
    )

    result = tax_module.main()

    assert result == 0
    text = tax_methods_file.read_text(encoding="utf-8")
    assert "current_year = 2025" in text
    assert "[NKE]" in text
