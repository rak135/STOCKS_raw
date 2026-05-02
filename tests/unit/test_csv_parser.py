from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from stock_tax_report.io.csv_parser import (
    _first_matching_header,
    _infer_broker_source,
    _normalize_header_name,
    detect_dialect,
    extract_transactions_from_file,
    group_by_ticker,
)


@pytest.mark.unit
def test_normalize_header_name_collapses_whitespace_and_case():
    assert _normalize_header_name("Trade Date") == "tradedate"
    assert _normalize_header_name("  Purchase   Price ") == "purchaseprice"


@pytest.mark.unit
def test_first_matching_header_picks_first_alias_present():
    fields = ["Symbol", "Trade Date", "Quantity"]
    assert _first_matching_header(fields, ["ticker", "symbol"]) == "Symbol"
    assert _first_matching_header(fields, ["price", "purchase price"]) is None


@pytest.mark.unit
def test_infer_broker_source_uses_filename_prefix(tmp_path):
    assert _infer_broker_source(tmp_path / "alpha_portfolio_new.csv") == "alpha"
    assert _infer_broker_source(tmp_path / "yahoo.csv") == "yahoo"


@pytest.mark.unit
def test_detect_dialect_falls_back_when_sniffer_fails():
    dialect = detect_dialect("Symbol,Quantity\nAAA,1\n")
    assert dialect.delimiter == ","


@pytest.mark.unit
def test_extract_transactions_maps_aliases_and_normalizes(tmp_path: Path):
    path = tmp_path / "alpha_portfolio_new.csv"
    path.write_text(
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "PLTR,20210510,18.76,10,BUY\n"
        "PLTR,20250929,180.00,10.99999,SELL\n",
        encoding="utf-8",
    )

    result = extract_transactions_from_file(path)

    assert len(result.transactions) == 2
    buy, sell = result.transactions
    assert buy.ticker == "PLTR"
    assert buy.action == "BUY"
    assert buy.date == date(2021, 5, 10)
    assert buy.quantity == Decimal("10")
    assert buy.broker_source == "alpha"
    assert sell.action == "SELL"
    assert sell.quantity == Decimal("11")  # rounded for SELL
    assert any("column mapping" in note for note in result.mapping_notes)


@pytest.mark.unit
def test_extract_transactions_emits_warnings_for_invalid_rows(tmp_path: Path):
    path = tmp_path / "broker_portfolio_new.csv"
    path.write_text(
        "Symbol,Trade Date,Quantity,Transaction Type\n"
        ",20250101,1,BUY\n"
        "AAA,20250101,1,\n"
        "AAA,not-a-date,1,BUY\n"
        "AAA,20250101,not-a-number,BUY\n"
        "AAA,20250101,1,DIVIDEND\n",
        encoding="utf-8",
    )

    result = extract_transactions_from_file(path)
    assert result.transactions == []
    assert len(result.warnings) == 5


@pytest.mark.unit
def test_group_by_ticker_orders_buys_before_sells_on_same_day(tx_factory):
    txs = [
        tx_factory(ticker="A", action="SELL", when=date(2025, 1, 1), row_number=2),
        tx_factory(ticker="A", action="BUY", when=date(2025, 1, 1), row_number=3),
        tx_factory(ticker="B", action="BUY", when=date(2025, 1, 1)),
    ]
    grouped = group_by_ticker(txs)
    assert list(grouped.keys()) == ["A", "B"]
    assert [tx.action for tx in grouped["A"]] == ["BUY", "SELL"]
