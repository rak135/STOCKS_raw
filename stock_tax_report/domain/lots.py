from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class BuyLot:
    source_file: str
    ticker: str
    buy_date: date
    quantity: Decimal
    price: Decimal
    original_row_number: int
    available_order: int = -1
