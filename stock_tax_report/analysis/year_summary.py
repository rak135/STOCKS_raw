from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

from stock_tax_report.analysis.trade_value import (
    _compute_match_pl_czk,
    _compute_trade_value,
    _compute_trade_value_czk,
)
from stock_tax_report.domain.analysis import TickerAnalysis, YearSummary
from stock_tax_report.domain.fx import FxRateBook


def _compute_year_summary(
    analysis: TickerAnalysis,
    year: int,
    current_year: int,
    fx_rate_book: FxRateBook,
) -> YearSummary:
    year_sells = [tx for tx in analysis.transactions if tx.date.year == year and tx.action == "SELL"]
    total_income = sum(((_compute_trade_value(tx.quantity, tx.price) or Decimal("0")) for tx in year_sells), Decimal("0"))

    if year >= current_year:
        return YearSummary(
            total_income=total_income,
            total_income_czk=None,
            total_pl=None,
            total_pl_czk=None,
            taxable_pl=None,
            taxable_pl_czk=None,
            over_three_year_pl=None,
            over_three_year_pl_czk=None,
        )

    total_income_czk = sum(
        ((_compute_trade_value_czk(tx.quantity, tx.price, tx.date, fx_rate_book) or Decimal("0")) for tx in year_sells),
        Decimal("0"),
    )

    sell_matches = analysis.sell_matches_by_year.get(year, [])
    total_pl = sum((sell_match.total_pl for sell_match in sell_matches), Decimal("0"))
    taxable_pl = sum((sell_match.total_taxable_pl for sell_match in sell_matches), Decimal("0"))
    total_pl_czk = sum(
        (_compute_match_pl_czk(match, sell_match.sell_date, fx_rate_book) for sell_match in sell_matches for match in sell_match.matches),
        Decimal("0"),
    )
    over_three_year_pl = sum(
        (match.total_pl for sell_match in sell_matches for match in sell_match.matches if match.time_test_passed),
        Decimal("0"),
    )
    over_three_year_pl_czk = sum(
        (
            _compute_match_pl_czk(match, sell_match.sell_date, fx_rate_book)
            for sell_match in sell_matches
            for match in sell_match.matches
            if match.time_test_passed
        ),
        Decimal("0"),
    )
    return YearSummary(
        total_income=total_income,
        total_income_czk=total_income_czk,
        total_pl=total_pl,
        total_pl_czk=total_pl_czk,
        taxable_pl=taxable_pl,
        taxable_pl_czk=total_pl_czk - over_three_year_pl_czk,
        over_three_year_pl=over_three_year_pl,
        over_three_year_pl_czk=over_three_year_pl_czk,
    )


def _sum_optional_decimals(values: List[Optional[Decimal]]) -> Optional[Decimal]:
    present_values = [value for value in values if value is not None]
    if not present_values:
        return None
    return sum(present_values, Decimal("0"))


def _compute_aggregate_year_summaries(
    analyses: List[TickerAnalysis],
    current_year: int,
    fx_rate_book: FxRateBook,
) -> Dict[int, YearSummary]:
    years = sorted({year for analysis in analyses for year in analysis.years}, reverse=True)
    aggregated: Dict[int, YearSummary] = {}

    for year in years:
        summaries = [
            _compute_year_summary(analysis, year, current_year, fx_rate_book)
            for analysis in analyses
            if year in analysis.years
        ]
        aggregated[year] = YearSummary(
            total_income=sum((summary.total_income for summary in summaries), Decimal("0")),
            total_income_czk=_sum_optional_decimals([summary.total_income_czk for summary in summaries]),
            total_pl=_sum_optional_decimals([summary.total_pl for summary in summaries]),
            total_pl_czk=_sum_optional_decimals([summary.total_pl_czk for summary in summaries]),
            taxable_pl=_sum_optional_decimals([summary.taxable_pl for summary in summaries]),
            taxable_pl_czk=_sum_optional_decimals([summary.taxable_pl_czk for summary in summaries]),
            over_three_year_pl=_sum_optional_decimals([summary.over_three_year_pl for summary in summaries]),
            over_three_year_pl_czk=_sum_optional_decimals([summary.over_three_year_pl_czk for summary in summaries]),
        )

    return aggregated
