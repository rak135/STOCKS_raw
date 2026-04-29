from __future__ import annotations

import csv
import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable

import pytest


TAX_EXPORT_PATH = Path(__file__).resolve().parents[1] / "export_ticker_tax_method_pdfs.py"


@pytest.fixture(scope="session")
def tax_module():
    spec = importlib.util.spec_from_file_location("tax_export_module", TAX_EXPORT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tx_factory(tax_module):
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
        return tax_module.Transaction(
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
