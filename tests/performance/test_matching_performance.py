from __future__ import annotations

from datetime import date, timedelta
from time import perf_counter

import pytest


@pytest.mark.performance
def test_time_test_max_handles_moderate_year_without_regression(tax_module, tx_factory):
    transactions = []

    for index in range(120):
        transactions.append(
            tx_factory(
                action="BUY",
                when=date(2021, 1, 1) + timedelta(days=index),
                quantity="1",
                price=str(10 + (index % 5)),
                source_file="pass.csv",
                row_number=index + 2,
            )
        )
    for index in range(120):
        transactions.append(
            tx_factory(
                action="BUY",
                when=date(2024, 1, 1) + timedelta(days=index),
                quantity="1",
                price=str(60 + (index % 7)),
                source_file="fail.csv",
                row_number=index + 200,
            )
        )
    for index in range(80):
        transactions.append(
            tx_factory(
                action="SELL",
                when=date(2025, 1, 1) + timedelta(days=index),
                quantity="2",
                price=str(100 + index),
                source_file="sell.csv",
                row_number=index + 400,
            )
        )

    config = tax_module.TaxConfig(current_year=2026, methods_by_ticker={"TEST": {2021: "fifo", 2024: "fifo", 2025: "time_test_max"}})

    started = perf_counter()
    analysis = tax_module.analyze_ticker("TEST", transactions, config)
    elapsed = perf_counter() - started

    assert len(analysis.sell_matches_by_year[2025]) == 80
    assert elapsed < 5.0
