from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from stock_tax_report.domain.fx import FxConfig


@dataclass
class TaxConfig:
    current_year: int
    methods_by_ticker: Dict[str, Dict[int, str]]
    fx_config: FxConfig = field(default_factory=FxConfig)
