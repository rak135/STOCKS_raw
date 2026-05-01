from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from stock_tax_report.domain.analysis import TickerAnalysis
from stock_tax_report.render.formatting import _fmt_decimal


def write_warnings(
    output_dir: Path,
    parser_warnings: List[str],
    mapping_notes: List[str],
    analyses: List[TickerAnalysis],
    generated_at: datetime,
) -> Path:
    warnings_path = output_dir / "_export_warnings.txt"
    lines: List[str] = []
    lines.append("Export warnings and diagnostics")
    lines.append(generated_at.strftime("Generated: %Y-%m-%d %H:%M:%S"))
    lines.append("")
    lines.append("Inferred column mappings and dialect")
    lines.extend(mapping_notes or ["None"])
    lines.append("")
    lines.append("Warnings")
    lines.extend(parser_warnings or ["None"])
    lines.append("")
    lines.append("Ignored current-year SELL transactions")

    ignored_lines: List[str] = []
    for analysis in analyses:
        for item in analysis.ignored_current_year_sells:
            ignored_lines.append(
                f"{analysis.ticker}: {item.sell_date.isoformat()} qty={_fmt_decimal(item.sell_quantity)} "
                f"source={item.sell_source_file}:{item.sell_row_number}"
            )

    lines.extend(ignored_lines or ["None"])
    warnings_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return warnings_path
