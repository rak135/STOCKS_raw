from __future__ import annotations

from decimal import Decimal

import pytest

from stock_tax_report.domain.fx import FxRateBook
from stock_tax_report.render.formatting import (
    METHOD_LABELS,
    _fmt_decimal,
    _fmt_usd_czk_pair,
    _format_holding_period,
    _format_match_status,
    _safe_pdf_name,
    _source_ref,
    _year_fx_label,
)


@pytest.mark.unit
def test_fmt_decimal_rounds_half_up():
    assert _fmt_decimal(Decimal("1.005")) == "1.01"
    assert _fmt_decimal(Decimal("1.004")) == "1.00"
    assert _fmt_decimal(Decimal("-1.005")) == "-1.01"  # ROUND_HALF_UP rounds away from zero
    assert _fmt_decimal(None) == ""
    assert _fmt_decimal(Decimal("3.14159"), places=4) == "3.1416"


@pytest.mark.unit
def test_fmt_usd_czk_pair_handles_partial_values():
    assert _fmt_usd_czk_pair(None, None) == ""
    assert _fmt_usd_czk_pair(Decimal("10"), None) == "10.00"
    assert _fmt_usd_czk_pair(None, Decimal("250")) == "250.00"
    assert _fmt_usd_czk_pair(Decimal("10"), Decimal("250")) == "10.00 / 250.00"


@pytest.mark.unit
def test_safe_pdf_name_strips_unsafe_characters():
    assert _safe_pdf_name("PLTR") == "PLTR"
    assert _safe_pdf_name("BRK.B") == "BRK.B"
    assert _safe_pdf_name("FOO/BAR") == "FOO_BAR"
    assert _safe_pdf_name("...") == "UNKNOWN"
    assert _safe_pdf_name("") == "UNKNOWN"


@pytest.mark.unit
def test_year_fx_label_marks_current_year_as_n_a():
    book = FxRateBook(mode_by_year={2025: "daily"}, daily_file=None, annual_rates={})
    assert _year_fx_label(2026, current_year=2026, fx_rate_book=book) == "FX=n/a"
    assert _year_fx_label(2025, current_year=2026, fx_rate_book=book) == "FX=daily"


@pytest.mark.unit
def test_format_holding_period_and_match_status():
    assert _format_holding_period(365) == "365 d"
    assert _format_match_status(True, 1100) == "PASS | 1100 d"
    assert _format_match_status(False, 30) == "FAIL | 30 d"


@pytest.mark.unit
def test_source_ref_and_method_labels():
    assert _source_ref("a.csv", 5) == "a.csv:5"
    assert METHOD_LABELS["fifo"] == "FIFO"
    assert METHOD_LABELS["time_test_max"] == "TIME_TEST_MAX"
