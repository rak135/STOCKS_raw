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
def test_default_paths_follow_repo_root_layout(tax_module):
    repo_root = tax_module.DEFAULT_INPUT_DIR.parent

    assert tax_module.DEFAULT_OUTPUT_DIR == repo_root / ".pdf exports tax methods"
    assert tax_module.DEFAULT_TAX_METHODS_FILE == repo_root / "tax_methods.toml"


@pytest.mark.unit
def test_tax_config_accepts_time_test_max_label(tax_module, tmp_path):
    toml_path = tmp_path / "tax_methods.toml"
    toml_path.write_text(
        'current_year = 2026\n'
        'fx_mode = "annual"\n'
        '\n'
        '[fx_annual_rates]\n'
        '2025 = 24.5\n'
        '\n'
        '[PLTR]\n'
        '2025 = "TIME_TEST_MAX"\n',
        encoding="utf-8",
    )

    config = tax_module.load_tax_config(toml_path)

    assert config.current_year == 2026
    assert config.methods_by_ticker["PLTR"][2025] == "time_test_max"
    assert config.fx_config.mode == "annual"
    assert config.fx_config.annual_rates[2025] == Decimal("24.5")


@pytest.mark.unit
def test_daily_fx_uses_previous_available_cnb_day(tax_module, tmp_path):
    fx_file = tmp_path / "cnb_2025.txt"
    fx_file.write_text(
        "Datum|1 USD\n"
        "02.01.2025|24,398\n"
        "03.01.2025|24,427\n",
        encoding="utf-8",
    )

    fx_rate_book = tax_module.load_fx_rate_book(
        tax_module.FxConfig(mode="daily", daily_file=fx_file, annual_rates={})
    )

    assert tax_module.resolve_usd_to_czk_rate(fx_rate_book, date(2025, 1, 4)) == Decimal("24.427")


@pytest.mark.unit
def test_daily_fx_loads_sibling_cnb_files_for_multiple_years(tax_module, tmp_path):
    fx_dir = tmp_path / "fx"
    fx_dir.mkdir()
    (fx_dir / "cnb_2024.txt").write_text(
        "Datum|1 USD\n"
        "30.12.2024|23,280\n",
        encoding="utf-8",
    )
    (fx_dir / "cnb_2025.txt").write_text(
        "Datum|1 USD\n"
        "02.01.2025|24,398\n",
        encoding="utf-8",
    )

    fx_rate_book = tax_module.load_fx_rate_book(
        tax_module.FxConfig(mode="daily", daily_file=fx_dir / "cnb_2025.txt", annual_rates={})
    )

    assert tax_module.resolve_usd_to_czk_rate(fx_rate_book, date(2024, 12, 30)) == Decimal("23.280")
    assert tax_module.resolve_usd_to_czk_rate(fx_rate_book, date(2025, 1, 2)) == Decimal("24.398")


@pytest.mark.unit
def test_daily_fx_supports_single_currency_cnb_format(tax_module, tmp_path):
    fx_file = tmp_path / "cnb_2024.txt"
    fx_file.write_text(
        "Měna: USD|Množství: 1\n"
        "Datum|Kurz\n"
        "02.01.2024|22,526\n",
        encoding="utf-8",
    )

    rates = tax_module._load_cnb_daily_usd_rates(fx_file)

    assert rates[date(2024, 1, 2)] == Decimal("22.526")


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
