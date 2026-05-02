from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from stock_tax_report.domain.fx import FxConfig
from stock_tax_report.io.fx_loader import (
    _load_cnb_daily_usd_rates,
    load_fx_rate_book,
    resolve_usd_to_czk_rate,
)


@pytest.mark.unit
def test_cnb_format_a_with_1usd_column(tmp_path: Path):
    fx_file = tmp_path / "cnb_2025.txt"
    fx_file.write_text(
        "Datum|1 USD\n"
        "02.01.2025|24,398\n"
        "03.01.2025|24,427\n",
        encoding="utf-8",
    )
    rates = _load_cnb_daily_usd_rates(fx_file)
    assert rates[date(2025, 1, 2)] == Decimal("24.398")
    assert rates[date(2025, 1, 3)] == Decimal("24.427")


@pytest.mark.unit
def test_cnb_format_b_single_currency_metadata_row(tmp_path: Path):
    fx_file = tmp_path / "cnb_2024.txt"
    fx_file.write_text(
        "Měna: USD|Množství: 1\n"
        "Datum|Kurz\n"
        "02.01.2024|22,526\n",
        encoding="utf-8",
    )
    rates = _load_cnb_daily_usd_rates(fx_file)
    assert rates == {date(2024, 1, 2): Decimal("22.526")}


@pytest.mark.unit
def test_cnb_missing_usd_column_raises(tmp_path: Path):
    fx_file = tmp_path / "cnb_2025.txt"
    fx_file.write_text("Datum|1 EUR\n02.01.2025|25,000\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing '1 USD' column"):
        _load_cnb_daily_usd_rates(fx_file)


@pytest.mark.unit
def test_cnb_invalid_date_raises(tmp_path: Path):
    fx_file = tmp_path / "cnb_2025.txt"
    fx_file.write_text("Datum|1 USD\nnot-a-date|24,398\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid date"):
        _load_cnb_daily_usd_rates(fx_file)


@pytest.mark.unit
def test_daily_resolution_uses_bisect_right_minus_one(tmp_path: Path):
    fx_file = tmp_path / "cnb_2025.txt"
    fx_file.write_text(
        "Datum|1 USD\n"
        "02.01.2025|24,000\n"
        "05.01.2025|24,500\n",
        encoding="utf-8",
    )
    book = load_fx_rate_book(FxConfig(mode_by_year={2025: "daily"}, daily_file=fx_file, annual_rates={}))
    # Exact match
    assert resolve_usd_to_czk_rate(book, date(2025, 1, 2)) == Decimal("24.000")
    # Between known dates -> previous available
    assert resolve_usd_to_czk_rate(book, date(2025, 1, 4)) == Decimal("24.000")
    # On the second known date
    assert resolve_usd_to_czk_rate(book, date(2025, 1, 5)) == Decimal("24.500")


@pytest.mark.unit
def test_daily_resolution_before_first_date_raises(tmp_path: Path):
    fx_file = tmp_path / "cnb_2025.txt"
    fx_file.write_text("Datum|1 USD\n10.01.2025|24,000\n", encoding="utf-8")
    book = load_fx_rate_book(FxConfig(mode_by_year={2025: "daily"}, daily_file=fx_file, annual_rates={}))
    with pytest.raises(ValueError, match="Missing daily FX rate"):
        resolve_usd_to_czk_rate(book, date(2025, 1, 5))


@pytest.mark.unit
def test_annual_mode_missing_rate_raises():
    book = load_fx_rate_book(
        FxConfig(mode_by_year={2024: "annual", 2025: "annual"}, annual_rates={2024: Decimal("23")})
    )
    assert resolve_usd_to_czk_rate(book, date(2024, 6, 1)) == Decimal("23")
    with pytest.raises(ValueError, match="Missing annual FX rate"):
        resolve_usd_to_czk_rate(book, date(2025, 6, 1))


@pytest.mark.unit
def test_resolve_raises_for_year_without_mode_entry():
    book = load_fx_rate_book(
        FxConfig(mode_by_year={2024: "annual"}, annual_rates={2024: Decimal("23")})
    )
    with pytest.raises(ValueError, match="Missing fx_mode_by_year entry for year 2025"):
        resolve_usd_to_czk_rate(book, date(2025, 6, 1))


@pytest.mark.unit
def test_load_fx_rate_book_daily_requires_existing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_fx_rate_book(
            FxConfig(mode_by_year={2024: "daily"}, daily_file=tmp_path / "missing.txt", annual_rates={})
        )


@pytest.mark.unit
def test_load_fx_rate_book_daily_requires_path():
    with pytest.raises(ValueError, match="fx_daily_file"):
        load_fx_rate_book(FxConfig(mode_by_year={2024: "daily"}, daily_file=None, annual_rates={}))


@pytest.mark.unit
def test_load_fx_rate_book_skips_daily_load_when_no_daily_year():
    # No daily years -> daily_file None is fine
    book = load_fx_rate_book(
        FxConfig(mode_by_year={2024: "annual"}, annual_rates={2024: Decimal("23")})
    )
    assert book.daily_dates == []
