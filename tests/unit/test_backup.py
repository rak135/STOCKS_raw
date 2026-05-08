from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from stock_tax_report.render.backup import backup_exported_files


@pytest.mark.unit
def test_backup_exported_files_copies_output_files_and_manifest(tmp_path: Path):
    output_dir = tmp_path / "out"
    backup_root = tmp_path / ".backup"
    output_dir.mkdir()
    (output_dir / "AAA.pdf").write_bytes(b"%PDF-1.4\n")
    (output_dir / "_export_summary.csv").write_text("ticker\nAAA\n", encoding="utf-8")

    backup_dir = backup_exported_files(
        output_dir,
        backup_root,
        datetime(2026, 5, 8, 17, 30, 0),
    )

    assert backup_dir == backup_root / "export_2026-05-08_17-30-00"
    assert (backup_dir / "AAA.pdf").read_bytes() == b"%PDF-1.4\n"
    assert (backup_dir / "_export_summary.csv").read_text(encoding="utf-8") == "ticker\nAAA\n"
    manifest = (backup_dir / "_backup_manifest.txt").read_text(encoding="utf-8")
    assert "Generated: 2026-05-08 17:30:00" in manifest
    assert "AAA.pdf" in manifest


@pytest.mark.unit
def test_backup_exported_files_uses_suffix_when_timestamp_exists(tmp_path: Path):
    output_dir = tmp_path / "out"
    backup_root = tmp_path / ".backup"
    output_dir.mkdir()
    (output_dir / "AAA.pdf").write_bytes(b"%PDF-1.4\n")
    (backup_root / "export_2026-05-08_17-30-00").mkdir(parents=True)

    backup_dir = backup_exported_files(
        output_dir,
        backup_root,
        datetime(2026, 5, 8, 17, 30, 0),
    )

    assert backup_dir == backup_root / "export_2026-05-08_17-30-00_2"
