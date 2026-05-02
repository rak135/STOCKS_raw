from __future__ import annotations

from typing import Dict, List

from stock_tax_report.domain.config import TaxConfig
from stock_tax_report.render.formatting import METHOD_LABELS


def _render_fx_section(config: TaxConfig) -> str:
    fx = config.fx_config
    lines: List[str] = []

    if fx.mode_by_year:
        lines.append("FX mode per year:")
        lines.append("")
        lines.append("| Year | Mode | Annual USD/CZK |")
        lines.append("|------|------|----------------|")
        for year in sorted(fx.mode_by_year):
            mode = fx.mode_by_year[year]
            rate_cell = str(fx.annual_rates[year]) if mode == "annual" and year in fx.annual_rates else "—"
            lines.append(f"| {year} | {mode} | {rate_cell} |")
        lines.append("")

    has_daily = any(mode == "daily" for mode in fx.mode_by_year.values())
    if has_daily:
        if fx.daily_file is not None:
            lines.append(f"Daily CNB rates loaded from `{fx.daily_file.name}` (and any sibling `cnb_*.txt`).")
        else:
            lines.append("Daily CNB rates loaded from configured directory.")
        lines.append("Resolution: for a given date, the latest available CNB rate on or before that date is used.")

    return "\n".join(lines)


def _render_methods_table(config: TaxConfig, year: int) -> str:
    rows: List[str] = []
    rows.append("| Ticker | Year | Method |")
    rows.append("|--------|------|--------|")
    for ticker in sorted(config.methods_by_ticker):
        ticker_methods: Dict[int, str] = config.methods_by_ticker[ticker]
        for tax_year in sorted(ticker_methods):
            if tax_year > year:
                continue
            label = METHOD_LABELS.get(ticker_methods[tax_year], ticker_methods[tax_year])
            rows.append(f"| {ticker} | {tax_year} | {label} |")
    if len(rows) == 2:
        rows.append("| — | — | — |")
    return "\n".join(rows)


def render_methodology_readme(config: TaxConfig, year: int, package_hash: str) -> str:
    sections: List[str] = []

    sections.append(f"# Tax Report Methodology — Year {year}")
    sections.append("")
    sections.append("## Tax matching methods")
    sections.append("")
    sections.append("Each (ticker, year) is matched using one of:")
    sections.append("")
    sections.append("- **FIFO** — first-in, first-out across all sources for the ticker.")
    sections.append("- **LIFO** — last-in, first-out across all sources for the ticker.")
    sections.append("- **max_gains** — picks BUY lots with the lowest cost basis first (maximises taxable gains).")
    sections.append("- **min_gains** — picks BUY lots with the highest cost basis first (minimises taxable gains).")
    sections.append("- **TIME_TEST_MAX** — global min-cost flow; allocates as much SELL quantity as possible to lots that pass the 3-year time test.")
    sections.append("")
    sections.append("## Time test (3-year rule)")
    sections.append("")
    sections.append("A SELL passes the time test when `sell_date > buy_date + 3 years` (calendar comparison).")
    sections.append("Profit/loss from time-test PASS lots is non-taxable.")
    sections.append("")
    sections.append("## Current year handling")
    sections.append("")
    sections.append(f"Year {year} is treated as the current year. SELL transactions inside it are reported in the trade history but excluded from tax matching. They will be matched in the following year's report.")
    sections.append("")
    sections.append("## FX rates")
    sections.append("")
    sections.append(_render_fx_section(config))
    sections.append("")
    sections.append("## Method assignments")
    sections.append("")
    sections.append(_render_methods_table(config, year))
    sections.append("")
    sections.append("## Bundle layout")
    sections.append("")
    sections.append("- `01_original_broker_exports/` — raw exports from each broker as received.")
    sections.append("- `02_normalized_csv/` — per-broker CSVs after column normalisation, fed into the script.")
    sections.append("- `03_config/tax_methods.toml` — config used for this run (ticker/year method, FX setup).")
    sections.append("- `04_script/` — snapshot of the script package and its hash.")
    sections.append("- `05_outputs/` — generated PDFs, summary CSV, warnings TXT.")
    sections.append("- `06_fx/` — CNB or annual FX file actually consulted by this run.")
    sections.append("- `07_notes/` — supplementary notes (optional).")
    sections.append("")
    sections.append("## Reproducibility")
    sections.append("")
    sections.append(f"Script package hash: `{package_hash}`")
    sections.append("")
    sections.append("Hash is computed from sorted `*.py` paths and contents inside the script package.")
    sections.append("")

    return "\n".join(sections)
