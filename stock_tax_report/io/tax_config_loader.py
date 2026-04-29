from __future__ import annotations

import tomllib
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from stock_tax_report.domain.config import TaxConfig
from stock_tax_report.domain.fx import FxConfig
from stock_tax_report.domain.transactions import Transaction
from stock_tax_report.io.parsing import normalize_ticker, parse_decimal


ALLOWED_METHODS = {"fifo", "lifo", "max_gains", "min_gains", "time_test_max"}
ALLOWED_FX_MODES = {"annual", "daily"}


def _normalize_method_name(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in ALLOWED_METHODS:
        return normalized
    return None


def _parse_current_year(raw_value: object) -> int:
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip().isdigit():
        return int(raw_value.strip())
    raise ValueError("tax_methods.toml: 'current_year' must be an integer")


def _parse_fx_mode(raw_value: object) -> str:
    if raw_value is None:
        return "annual"
    if not isinstance(raw_value, str):
        raise ValueError("tax_methods.toml: 'fx_mode' must be 'daily' or 'annual'")
    normalized = raw_value.strip().lower()
    if normalized not in ALLOWED_FX_MODES:
        raise ValueError("tax_methods.toml: 'fx_mode' must be 'daily' or 'annual'")
    return normalized


def _parse_decimal_config_value(raw_value: object, field_name: str) -> Decimal:
    if isinstance(raw_value, Decimal):
        return raw_value
    if isinstance(raw_value, (int, float, str)):
        parsed = parse_decimal(str(raw_value))
        if parsed is not None:
            return parsed
    raise ValueError(f"tax_methods.toml: '{field_name}' must be a decimal number")


def _parse_fx_daily_file(raw_value: object) -> Optional[Path]:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ValueError("tax_methods.toml: 'fx_daily_file' must be a string path")
    text = raw_value.strip()
    if not text:
        return None
    return Path(text)


def _parse_fx_annual_rates(raw_value: object) -> Dict[int, Decimal]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ValueError("tax_methods.toml: 'fx_annual_rates' must be a table")

    annual_rates: Dict[int, Decimal] = {}
    for year_key, rate_value in raw_value.items():
        year_text = str(year_key).strip()
        if not year_text.isdigit():
            raise ValueError(f"tax_methods.toml: fx_annual_rates has invalid year key '{year_key}'")
        annual_rates[int(year_text)] = _parse_decimal_config_value(rate_value, f"fx_annual_rates.{year_text}")
    return annual_rates


def load_tax_config(tax_methods_file: Path) -> TaxConfig:
    if not tax_methods_file.exists():
        raise FileNotFoundError(f"Tax methods file does not exist: {tax_methods_file}")

    try:
        data = tomllib.loads(tax_methods_file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"tax_methods.toml: invalid TOML ({exc})") from exc

    if "current_year" not in data:
        raise ValueError("tax_methods.toml: missing top-level 'current_year'")

    current_year = _parse_current_year(data["current_year"])
    fx_config = FxConfig(
        mode=_parse_fx_mode(data.get("fx_mode")),
        daily_file=_parse_fx_daily_file(data.get("fx_daily_file")),
        annual_rates=_parse_fx_annual_rates(data.get("fx_annual_rates")),
    )
    methods_by_ticker: Dict[str, Dict[int, str]] = {}

    for key, value in data.items():
        if key in {"current_year", "fx_mode", "fx_daily_file", "fx_annual_rates"}:
            continue

        if not isinstance(value, dict):
            raise ValueError(f"tax_methods.toml: section '{key}' must be a table")

        ticker = normalize_ticker(key)
        ticker_methods: Dict[int, str] = {}
        for year_key, method_value in value.items():
            year_text = str(year_key).strip()
            if not year_text.isdigit():
                raise ValueError(f"tax_methods.toml: ticker '{ticker}' has invalid year key '{year_key}'")

            method = _normalize_method_name(method_value)
            if method is None:
                raise ValueError(
                    f"tax_methods.toml: ticker '{ticker}' year '{year_text}' has invalid method '{method_value}'"
                )

            ticker_methods[int(year_text)] = method

        methods_by_ticker[ticker] = ticker_methods

    return TaxConfig(current_year=current_year, methods_by_ticker=methods_by_ticker, fx_config=fx_config)


def _infer_template_current_year(transactions: Iterable[Transaction]) -> int:
    years = [tx.date.year for tx in transactions]
    if not years:
        return datetime.now().year
    return max(years)


def build_template_text(grouped: Dict[str, List[Transaction]], current_year: int) -> str:
    lines: List[str] = []
    lines.append("current_year = %s" % current_year)
    lines.append('fx_mode = "annual"')
    lines.append('fx_daily_file = ""')
    lines.append("")

    all_years = sorted({tx.date.year for transactions in grouped.values() for tx in transactions})
    if all_years:
        lines.append("[fx_annual_rates]")
        for year in all_years:
            lines.append(f'{year} = ""')
        lines.append("")

    for ticker, transactions in grouped.items():
        years = sorted({tx.date.year for tx in transactions if tx.date.year < current_year})
        if not years:
            continue

        lines.append(f"[{ticker}]")
        for year in years:
            lines.append(f'{year} = ""')
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_template_file(tax_methods_file: Path, grouped: Dict[str, List[Transaction]], current_year: int) -> Path:
    tax_methods_file.parent.mkdir(parents=True, exist_ok=True)
    tax_methods_file.write_text(build_template_text(grouped, current_year), encoding="utf-8")
    return tax_methods_file


def validate_tax_config(grouped: Dict[str, List[Transaction]], config: TaxConfig) -> List[str]:
    errors: List[str] = []

    for ticker, transactions in grouped.items():
        required_years = sorted({tx.date.year for tx in transactions if tx.date.year < config.current_year})
        ticker_methods = config.methods_by_ticker.get(ticker, {})
        for year in required_years:
            if year not in ticker_methods:
                errors.append(f"ticker '{ticker}' is missing tax method for year {year}")

    return errors
