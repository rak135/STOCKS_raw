from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest


@pytest.mark.unit
def test_parse_decimal_handles_localized_and_symbol_values(tax_module):
    assert tax_module.parse_decimal("$1,234.50") == Decimal("1234.50")
    assert tax_module.parse_decimal("1 234,50") == Decimal("1234.50")
    assert tax_module.parse_decimal("") is None


@pytest.mark.unit
def test_parse_date_supports_compact_yyyymmdd(tax_module):
    assert tax_module.parse_date("20250210") == date(2025, 2, 10)


@pytest.mark.unit
def test_normalize_quantity_rounds_sell_yahoo_tail(tax_module):
    rounded = tax_module.normalize_quantity_for_export("SELL", Decimal("12.99999"))
    untouched = tax_module.normalize_quantity_for_export("BUY", Decimal("12.99999"))
    assert rounded == Decimal("13")
    assert untouched == Decimal("12.99999")


@pytest.mark.unit
def test_tax_config_accepts_time_test_max_label(tax_module, tmp_path):
    toml_path = tmp_path / "tax_methods.toml"
    toml_path.write_text(
        'current_year = 2026\n\n[PLTR]\n2025 = "TIME_TEST_MAX"\n',
        encoding="utf-8",
    )

    config = tax_module.load_tax_config(toml_path)

    assert config.current_year == 2026
    assert config.methods_by_ticker["PLTR"][2025] == "time_test_max"


@pytest.mark.unit
def test_validate_tax_config_reports_missing_years(tax_module, tx_factory):
    transactions = [
        tx_factory(action="BUY", when=date(2024, 1, 1)),
        tx_factory(action="SELL", when=date(2025, 2, 1), quantity="1", price="20", row_number=3),
    ]
    grouped = {"TEST": transactions}
    config = tax_module.TaxConfig(current_year=2026, methods_by_ticker={"TEST": {}})

    errors = tax_module.validate_tax_config(grouped, config)

    assert errors == ["ticker 'TEST' is missing tax method for year 2024", "ticker 'TEST' is missing tax method for year 2025"]
