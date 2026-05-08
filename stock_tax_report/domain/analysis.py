from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from stock_tax_report.domain.matches import BuyUsage, IgnoredCurrentYearSell, SellMatch
from stock_tax_report.domain.transactions import Transaction


@dataclass
class YearSummary:
    total_income: Decimal
    total_income_czk: Optional[Decimal]
    total_costs: Optional[Decimal]
    total_costs_czk: Optional[Decimal]
    total_pl: Optional[Decimal]
    total_pl_czk: Optional[Decimal]
    pass_income: Optional[Decimal]
    pass_income_czk: Optional[Decimal]
    pass_costs: Optional[Decimal]
    pass_costs_czk: Optional[Decimal]
    taxable_pl: Optional[Decimal]
    taxable_pl_czk: Optional[Decimal]
    fail_income: Optional[Decimal]
    fail_income_czk: Optional[Decimal]
    fail_costs: Optional[Decimal]
    fail_costs_czk: Optional[Decimal]
    over_three_year_pl: Optional[Decimal]
    over_three_year_pl_czk: Optional[Decimal]


@dataclass
class TickerAnalysis:
    ticker: str
    years: List[int]
    transactions: List[Transaction]
    open_quantity: Decimal
    year_methods: Dict[int, str]
    sell_matches_by_year: Dict[int, List[SellMatch]]
    buy_usages_by_key: Dict[tuple[date, str, int], List[BuyUsage]]
    ignored_current_year_sells: List[IgnoredCurrentYearSell]
    source_files: List[str]
