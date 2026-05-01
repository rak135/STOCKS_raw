from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from stock_tax_report.domain.fx import FxRateBook


METHOD_LABELS = {
    "fifo": "FIFO",
    "lifo": "LIFO",
    "max_gains": "max_gains",
    "min_gains": "min_gains",
    "time_test_max": "TIME_TEST_MAX",
}


def _safe_pdf_name(ticker: str) -> str:
    safe = re.sub(r"[^A-Z0-9._-]", "_", ticker)
    safe = safe.strip("._")
    return safe or "UNKNOWN"


def _fmt_decimal(value: Optional[Decimal], places: int = 2) -> str:
    if value is None:
        return ""
    quantizer = Decimal("1").scaleb(-places)
    rounded = value.quantize(quantizer, rounding=ROUND_HALF_UP)
    return format(rounded, f".{places}f")


def _fmt_usd_czk_pair(usd_value: Optional[Decimal], czk_value: Optional[Decimal]) -> str:
    if usd_value is None and czk_value is None:
        return ""
    if czk_value is None:
        return _fmt_decimal(usd_value)
    if usd_value is None:
        return _fmt_decimal(czk_value)
    return f"{_fmt_decimal(usd_value)} / {_fmt_decimal(czk_value)}"


def _year_fx_label(year: int, current_year: int, fx_rate_book: FxRateBook) -> str:
    if year >= current_year:
        return "FX=n/a"
    return f"FX={fx_rate_book.mode}"


def _source_ref(source_file: str, row_number: int) -> str:
    return f"{source_file}:{row_number}"


def _format_holding_period(days: int) -> str:
    return f"{days} d"


def _format_match_status(time_test_passed: bool, holding_period_days: int) -> str:
    return f"{'PASS' if time_test_passed else 'FAIL'} | {_format_holding_period(holding_period_days)}"
