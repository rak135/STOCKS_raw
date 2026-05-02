from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from stock_tax_report.analysis.ticker_analysis import analyze_ticker
from stock_tax_report.domain.config import TaxConfig
from stock_tax_report.domain.fx import FxConfig
from stock_tax_report.io.fx_loader import load_fx_rate_book
from stock_tax_report.render.summary_csv import write_summary
from stock_tax_report.render.warnings_txt import write_warnings


@pytest.fixture
def simple_analysis(tx_factory):
    txs = [
        tx_factory(ticker="AAA", action="BUY", when=date(2024, 1, 1), price="10", source_file="alpha_portfolio.csv"),
        tx_factory(ticker="AAA", action="SELL", when=date(2025, 1, 1), price="30", source_file="alpha_portfolio.csv", row_number=3),
        tx_factory(ticker="AAA", action="SELL", when=date(2026, 5, 1), price="40", source_file="alpha_portfolio.csv", row_number=4),
    ]
    config = TaxConfig(current_year=2026, methods_by_ticker={"AAA": {2024: "fifo", 2025: "fifo"}})
    return analyze_ticker("AAA", txs, config)


@pytest.mark.unit
def test_write_summary_emits_expected_header_and_row(tmp_path: Path, simple_analysis):
    book = load_fx_rate_book(FxConfig(
        mode_by_year={2024: "annual", 2025: "annual"},
        annual_rates={2024: Decimal("23"), 2025: Decimal("25")},
    ))
    path = write_summary(tmp_path, [simple_analysis], book)

    content = path.read_text(encoding="utf-8").splitlines()
    assert content[0] == "ticker,pdf_file,fx_modes,year_count,sell_count,ignored_current_year_sell_count,open_qty,source_files"
    fields = content[1].split(",")
    assert fields[0] == "AAA"
    assert fields[1] == "AAA.pdf"
    assert fields[2].startswith("2024=annual")  # per-year encoded
    assert "2025=annual" in fields[2]
    assert fields[5] == "1"  # one ignored 2026 sell


@pytest.mark.unit
def test_write_warnings_is_deterministic_for_fixed_generated_at(tmp_path: Path, simple_analysis):
    generated_at = datetime(2026, 4, 1, 12, 0, 0)
    path = write_warnings(
        tmp_path,
        parser_warnings=["broker.csv:5: skipped row because no ticker"],
        mapping_notes=["broker.csv: detected delimiter=','"],
        analyses=[simple_analysis],
        generated_at=generated_at,
    )
    text = path.read_text(encoding="utf-8")
    assert "Generated: 2026-04-01 12:00:00" in text
    assert "broker.csv:5: skipped row because no ticker" in text
    assert "AAA: 2026-05-01" in text


@pytest.mark.unit
def test_write_warnings_outputs_none_when_empty(tmp_path: Path, simple_analysis):
    # Use an analysis without ignored sells
    generated_at = datetime(2026, 4, 1, 12, 0, 0)
    path = write_warnings(
        tmp_path,
        parser_warnings=[],
        mapping_notes=[],
        analyses=[],
        generated_at=generated_at,
    )
    text = path.read_text(encoding="utf-8")
    # Each empty section falls back to literal "None"
    assert text.count("None") >= 3
