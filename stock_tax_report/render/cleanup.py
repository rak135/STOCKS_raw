from __future__ import annotations

from pathlib import Path


def _clear_previous_exports(output_dir: Path) -> None:
    for pdf_path in output_dir.glob("*.pdf"):
        pdf_path.unlink(missing_ok=True)

    for artifact_name in ["_export_summary.csv", "_export_warnings.txt"]:
        (output_dir / artifact_name).unlink(missing_ok=True)
