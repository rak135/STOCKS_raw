from __future__ import annotations

import csv
import re
from bisect import bisect_right
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict

from stock_tax_report.domain.fx import FxConfig, FxRateBook
from stock_tax_report.io.parsing import parse_date, parse_decimal


def _load_cnb_daily_usd_rates(fx_daily_file: Path) -> Dict[date, Decimal]:
    try:
        raw_text = fx_daily_file.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError(f"FX daily file could not be read: {fx_daily_file} ({exc})") from exc

    rows = [row for row in csv.reader(raw_text.splitlines(), delimiter="|") if row]
    if not rows:
        raise ValueError(f"FX daily file is empty: {fx_daily_file}")

    if len(rows) >= 2:
        first_cell = rows[0][0].strip().upper() if rows[0] else ""
        second_header = [cell.strip().upper() for cell in rows[1]]
        if first_cell.startswith("M") and second_header[:2] == ["DATUM", "KURZ"]:
            rates: Dict[date, Decimal] = {}
            for row_number, row in enumerate(rows[2:], start=3):
                if len(row) < 2:
                    continue
                rate_date = parse_date(row[0])
                if rate_date is None:
                    raise ValueError(f"FX daily file has invalid date on line {row_number}: {fx_daily_file}")
                rate = parse_decimal(row[1])
                if rate is None:
                    raise ValueError(f"FX daily file has invalid USD rate on line {row_number}: {fx_daily_file}")
                rates[rate_date] = rate

            if not rates:
                raise ValueError(f"FX daily file has no USD rates: {fx_daily_file}")
            return rates

    header = rows[0]
    usd_index = None
    for index, column_name in enumerate(header):
        normalized = re.sub(r"\s+", "", column_name.strip().upper())
        if normalized == "1USD":
            usd_index = index
            break
    if usd_index is None:
        raise ValueError(f"FX daily file is missing '1 USD' column: {fx_daily_file}")

    rates: Dict[date, Decimal] = {}
    for row_number, row in enumerate(rows[1:], start=2):
        if len(row) <= usd_index:
            continue
        rate_date = parse_date(row[0])
        if rate_date is None:
            raise ValueError(f"FX daily file has invalid date on line {row_number}: {fx_daily_file}")
        rate = parse_decimal(row[usd_index])
        if rate is None:
            raise ValueError(f"FX daily file has invalid USD rate on line {row_number}: {fx_daily_file}")
        rates[rate_date] = rate

    if not rates:
        raise ValueError(f"FX daily file has no USD rates: {fx_daily_file}")
    return rates


def _load_all_cnb_daily_usd_rates(fx_daily_file: Path) -> Dict[date, Decimal]:
    sibling_files = sorted(
        path for path in fx_daily_file.parent.glob("cnb_*.txt") if path.is_file()
    )
    if fx_daily_file not in sibling_files:
        sibling_files.append(fx_daily_file)
        sibling_files.sort()

    rates: Dict[date, Decimal] = {}
    for file_path in sibling_files:
        rates.update(_load_cnb_daily_usd_rates(file_path))

    if not rates:
        raise ValueError(f"FX daily files have no USD rates in: {fx_daily_file.parent}")
    return rates


def load_fx_rate_book(fx_config: FxConfig) -> FxRateBook:
    book = FxRateBook(mode=fx_config.mode, daily_file=fx_config.daily_file, annual_rates=dict(fx_config.annual_rates))
    if fx_config.mode != "daily":
        return book

    if fx_config.daily_file is None:
        raise ValueError("tax_methods.toml: 'fx_daily_file' is required when fx_mode = 'daily'")
    if not fx_config.daily_file.exists():
        raise FileNotFoundError(f"FX daily file does not exist: {fx_config.daily_file}")

    book.daily_rates_by_date = _load_all_cnb_daily_usd_rates(fx_config.daily_file)
    book.daily_dates = sorted(book.daily_rates_by_date)
    return book


def resolve_usd_to_czk_rate(fx_rate_book: FxRateBook, value_date: date) -> Decimal:
    annual_rate = fx_rate_book.annual_rates.get(value_date.year)
    if fx_rate_book.mode == "annual":
        if annual_rate is None:
            raise ValueError(f"Missing annual FX rate for year {value_date.year}")
        return annual_rate

    matched_index = bisect_right(fx_rate_book.daily_dates, value_date) - 1
    if matched_index >= 0:
        matched_date = fx_rate_book.daily_dates[matched_index]
        return fx_rate_book.daily_rates_by_date[matched_date]

    raise ValueError(f"Missing daily FX rate for {value_date.isoformat()} in {fx_rate_book.daily_file}")
