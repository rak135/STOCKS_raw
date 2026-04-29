from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Optional


def parse_decimal(value: str) -> Optional[Decimal]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    text = text.replace(" ", "").replace(" ", "")
    text = re.sub(r"[^0-9,\.\-+eE]", "", text)
    if not text:
        return None

    comma_pos = text.rfind(",")
    dot_pos = text.rfind(".")

    if comma_pos >= 0 and dot_pos >= 0:
        if comma_pos > dot_pos:
            text = text.replace(".", "")
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif comma_pos >= 0:
        text = text.replace(".", "")
        text = text.replace(",", ".")

    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_date(value: str) -> Optional[date]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y%m%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    digits_only = re.sub(r"\D", "", text)
    if len(digits_only) == 8:
        for fmt in ["%Y%m%d", "%d%m%Y", "%m%d%Y"]:
            try:
                return datetime.strptime(digits_only, fmt).date()
            except ValueError:
                continue

    return None


def normalize_action(value: str) -> Optional[str]:
    if value is None:
        return None
    text = value.strip().upper()
    if not text:
        return None

    alias_map = {
        "BUY": "BUY",
        "B": "BUY",
        "PURCHASE": "BUY",
        "BOUGHT": "BUY",
        "KUPNO": "BUY",
        "SELL": "SELL",
        "S": "SELL",
        "SOLD": "SELL",
        "SPRZEDAZ": "SELL",
        "SPRZEDAŻ": "SELL",
    }
    return alias_map.get(text)


def normalize_ticker(value: str) -> str:
    if value is None:
        return ""
    return value.strip().upper()


def normalize_quantity_for_export(action: str, quantity: Decimal) -> Decimal:
    if action != "SELL":
        return quantity

    fractional_part = quantity % 1
    if fractional_part == Decimal("0.99999"):
        return quantity.to_integral_value(rounding=ROUND_CEILING)

    return quantity
