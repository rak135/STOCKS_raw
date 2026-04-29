from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List


@dataclass
class MatchDetail:
    buy_date: date
    matched_qty: Decimal
    buy_price: Decimal
    sell_price: Decimal
    holding_period_days: int
    time_test_passed: bool
    total_pl: Decimal
    taxable_pl: Decimal
    buy_source_file: str
    buy_row_number: int


@dataclass
class SellMatch:
    sell_date: date
    sell_quantity: Decimal
    sell_price: Decimal
    sell_source_file: str
    sell_row_number: int
    method: str
    matches: List[MatchDetail]
    total_pl: Decimal
    total_taxable_pl: Decimal


@dataclass
class BuyUsage:
    sell_date: date
    matched_qty: Decimal
    sell_price: Decimal
    holding_period_days: int
    time_test_passed: bool
    total_pl: Decimal
    taxable_pl: Decimal
    sell_source_file: str
    sell_row_number: int


@dataclass
class IgnoredCurrentYearSell:
    sell_date: date
    sell_quantity: Decimal
    sell_price: Decimal
    sell_source_file: str
    sell_row_number: int
