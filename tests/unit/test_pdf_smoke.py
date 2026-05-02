from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from stock_tax_report.analysis.ticker_analysis import analyze_ticker
from stock_tax_report.domain.config import TaxConfig
from stock_tax_report.domain.fx import FxConfig
from stock_tax_report.io.fx_loader import load_fx_rate_book
from stock_tax_report.render.pdf_all_tickers import build_all_tickers_year_summary_pdf
from stock_tax_report.render.pdf_ticker import build_pdf_for_ticker


@pytest.mark.unit
def test_build_pdf_for_ticker_writes_non_empty_pdf(tmp_path: Path, tx_factory):
    txs = [
        tx_factory(ticker="AAA", action="BUY", when=date(2024, 1, 1), price="10", source_file="alpha.csv"),
        tx_factory(ticker="AAA", action="SELL", when=date(2025, 1, 1), price="30", source_file="alpha.csv", row_number=3),
    ]
    analysis = analyze_ticker(
        "AAA",
        txs,
        TaxConfig(current_year=2026, methods_by_ticker={"AAA": {2024: "fifo", 2025: "fifo"}}),
    )
    book = load_fx_rate_book(FxConfig(mode="annual", annual_rates={2024: Decimal("23"), 2025: Decimal("25")}))

    pdf_path = build_pdf_for_ticker(analysis, tmp_path, datetime(2026, 4, 1, 12, 0, 0), 2026, book)

    assert pdf_path == tmp_path / "AAA.pdf"
    data = pdf_path.read_bytes()
    assert data.startswith(b"%PDF-")
    assert b"%%EOF" in data


@pytest.mark.unit
def test_build_all_tickers_year_summary_pdf_writes_pdf(tmp_path: Path, tx_factory):
    txs = [
        tx_factory(ticker="AAA", action="BUY", when=date(2024, 1, 1), price="10", source_file="alpha.csv"),
        tx_factory(ticker="AAA", action="SELL", when=date(2025, 1, 1), price="30", source_file="alpha.csv", row_number=3),
    ]
    analysis = analyze_ticker(
        "AAA",
        txs,
        TaxConfig(current_year=2026, methods_by_ticker={"AAA": {2024: "fifo", 2025: "fifo"}}),
    )
    book = load_fx_rate_book(FxConfig(mode="annual", annual_rates={2024: Decimal("23"), 2025: Decimal("25")}))

    pdf_path = build_all_tickers_year_summary_pdf(
        [analysis], tmp_path, datetime(2026, 4, 1, 12, 0, 0), 2026, book
    )

    assert pdf_path.name == "_all_tickers_year_summary.pdf"
    data = pdf_path.read_bytes()
    assert data.startswith(b"%PDF-")
    assert b"%%EOF" in data


@pytest.mark.unit
def test_pdf_for_ticker_with_no_history_still_renders(tmp_path: Path, tx_factory):
    txs = [tx_factory(ticker="AAA", action="BUY", when=date(2024, 1, 1), price="10")]
    analysis = analyze_ticker(
        "AAA",
        txs,
        TaxConfig(current_year=2026, methods_by_ticker={"AAA": {2024: "fifo"}}),
    )
    book = load_fx_rate_book(FxConfig(mode="annual", annual_rates={2024: Decimal("23")}))
    pdf_path = build_pdf_for_ticker(analysis, tmp_path, datetime(2026, 4, 1, 12, 0, 0), 2026, book)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
