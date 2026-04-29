from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class FxConfig:
    mode: str = "annual"
    daily_file: Optional[Path] = None
    annual_rates: Dict[int, Decimal] = field(default_factory=dict)


@dataclass
class FxRateBook:
    mode: str
    daily_file: Optional[Path]
    annual_rates: Dict[int, Decimal]
    daily_rates_by_date: Dict[date, Decimal] = field(default_factory=dict)
    daily_dates: List[date] = field(default_factory=list)
