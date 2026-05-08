from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional


@dataclass
class MarketPrice:
    ticker: str
    price_usd: Decimal
    provider: str
    fetched_at: datetime


@dataclass
class PortfolioPosition:
    ticker: str
    quantity: Decimal


@dataclass
class PortfolioAllocationItem:
    ticker: str
    quantity: Decimal
    price_usd: Decimal
    value_usd: Decimal
    allocation_percent: Decimal


@dataclass
class MarketPriceSnapshot:
    provider: str
    fetched_at: datetime
    prices: List[MarketPrice]
    errors: List[str]


@dataclass
class PortfolioAllocationResult:
    items: List[PortfolioAllocationItem]
    total_value_usd: Decimal
    price_snapshot: Optional[MarketPriceSnapshot]
    warnings: List[str]
