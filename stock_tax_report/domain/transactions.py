from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional


@dataclass
class Transaction:
    source_file: str
    broker_source: str
    ticker: str
    action: str
    date: date
    quantity: Decimal
    price: Optional[Decimal]
    currency: Optional[str]
    fee: Optional[Decimal]
    gross_amount: Optional[Decimal]
    original_row_number: int


@dataclass
class FileExtractionResult:
    transactions: List[Transaction]
    warnings: List[str]
    mapping_notes: List[str]
