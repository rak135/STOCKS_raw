from __future__ import annotations

from pathlib import Path
from typing import List


def discover_csv_files(input_dir: Path) -> List[Path]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    return sorted(p for p in input_dir.glob("*.csv") if p.is_file())
