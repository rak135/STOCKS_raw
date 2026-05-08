from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable

import pytest

from stock_tax_report.domain.transactions import Transaction


@pytest.fixture
def tx_factory():
    def _make(
        *,
        ticker: str = "TEST",
        action: str = "BUY",
        when: date = date(2025, 1, 1),
        quantity: str = "1",
        price: str = "10",
        source_file: str = "broker.csv",
        row_number: int = 2,
    ):
        return Transaction(
            source_file=source_file,
            broker_source=source_file.split("_", 1)[0],
            ticker=ticker,
            action=action,
            date=when,
            quantity=Decimal(quantity),
            price=Decimal(price),
            currency="USD",
            fee=None,
            gross_amount=None,
            original_row_number=row_number,
        )

    return _make


@pytest.fixture(autouse=True)
def disable_external_market_data(monkeypatch):
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    import stock_tax_report.pipeline as pipeline

    monkeypatch.setattr(
        pipeline,
        "fetch_market_prices",
        lambda tickers, *, fetched_at, config_file=None: (
            None,
            ["Portfolio allocation skipped in tests"],
        ),
    )


def write_portfolio_csv(file_path: Path, rows: Iterable[dict[str, str]]) -> None:
    fieldnames = [
        "Symbol",
        "Current Price",
        "Date",
        "Time",
        "Change",
        "Open",
        "High",
        "Low",
        "Volume",
        "Trade Date",
        "Purchase Price",
        "Quantity",
        "Commission",
        "High Limit",
        "Low Limit",
        "Comment",
        "Transaction Type",
    ]
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


@pytest.fixture
def csv_writer():
    return write_portfolio_csv
