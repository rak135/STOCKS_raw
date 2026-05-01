from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from stock_tax_report.bundle.layout import (
    CONFIG,
    FX,
    MANIFEST_FILE,
    NORMALIZED_CSV,
    NOTES,
    ORIGINAL_BROKER_EXPORTS,
    OUTPUTS,
    README_METHODOLOGY,
    SCRIPT,
    SCRIPT_HASH_FILE,
)
from stock_tax_report.pipeline import run as run_pipeline


@pytest.mark.integration
def test_run_without_bundle_root_writes_only_outputs(tmp_path: Path, csv_writer):
    input_dir = tmp_path / "csv"
    output_dir = tmp_path / "out"
    tax_methods_file = tmp_path / "tax_methods.toml"

    csv_writer(
        input_dir / "alpha_portfolio_new.csv",
        [
            {"Symbol": "PLTR", "Trade Date": "20210510", "Purchase Price": "18.76", "Quantity": "10", "Transaction Type": "BUY"},
            {"Symbol": "PLTR", "Trade Date": "20250929", "Purchase Price": "180.00", "Quantity": "10", "Transaction Type": "SELL"},
        ],
    )
    tax_methods_file.write_text(
        'current_year = 2026\n'
        'fx_mode = "annual"\n'
        '\n'
        '[fx_annual_rates]\n'
        '2021 = 21\n'
        '2025 = 24\n'
        '\n'
        '[PLTR]\n'
        '2021 = "FIFO"\n'
        '2025 = "FIFO"\n',
        encoding="utf-8",
    )

    result = run_pipeline(
        input_dir=input_dir,
        output_dir=output_dir,
        tax_methods_file=tax_methods_file,
        generated_at=datetime(2026, 4, 1, 12, 0, 0),
    )

    assert result.bundle_dir is None
    assert result.bundle_manifest is None
    assert (output_dir / "PLTR.pdf").is_file()
    assert (output_dir / "_export_summary.csv").is_file()
    assert (output_dir / "_export_warnings.txt").is_file()


@pytest.mark.integration
def test_run_with_bundle_root_assembles_full_tree(tmp_path: Path, csv_writer):
    input_dir = tmp_path / "csv"
    output_dir = tmp_path / "out"
    bundle_root = tmp_path / "bundles"
    notes_dir = tmp_path / "notes"
    broker_exports_dir = tmp_path / "brokers"
    tax_methods_file = tmp_path / "tax_methods.toml"

    csv_writer(
        input_dir / "alpha_portfolio_new.csv",
        [
            {"Symbol": "PLTR", "Trade Date": "20210510", "Purchase Price": "18.76", "Quantity": "10", "Transaction Type": "BUY"},
            {"Symbol": "PLTR", "Trade Date": "20250929", "Purchase Price": "180.00", "Quantity": "10", "Transaction Type": "SELL"},
        ],
    )
    tax_methods_file.write_text(
        'current_year = 2026\n'
        'fx_mode = "annual"\n'
        '\n'
        '[fx_annual_rates]\n'
        '2021 = 21\n'
        '2025 = 24\n'
        '\n'
        '[PLTR]\n'
        '2021 = "FIFO"\n'
        '2025 = "FIFO"\n',
        encoding="utf-8",
    )
    notes_dir.mkdir()
    (notes_dir / "audit.md").write_text("# Audit\n", encoding="utf-8")
    broker_exports_dir.mkdir()
    (broker_exports_dir / "broker_a.pdf").write_bytes(b"%PDF-1.4 fake\n")

    generated_at = datetime(2026, 4, 1, 12, 0, 0)
    result = run_pipeline(
        input_dir=input_dir,
        output_dir=output_dir,
        tax_methods_file=tax_methods_file,
        generated_at=generated_at,
        bundle_root=bundle_root,
        notes_dir=notes_dir,
        broker_exports_dir=broker_exports_dir,
    )

    bundle_dir = bundle_root / "tax_2026"
    assert result.bundle_dir == bundle_dir
    assert result.bundle_manifest is not None

    assert (bundle_dir / README_METHODOLOGY).is_file()
    assert (bundle_dir / ORIGINAL_BROKER_EXPORTS / "broker_a.pdf").is_file()
    assert (bundle_dir / NORMALIZED_CSV / "alpha_portfolio_new.csv").is_file()
    assert (bundle_dir / CONFIG / "tax_methods.toml").is_file()
    assert (bundle_dir / NOTES / "audit.md").is_file()
    assert (bundle_dir / OUTPUTS / "PLTR.pdf").is_file()
    assert (bundle_dir / OUTPUTS / "_export_summary.csv").is_file()
    assert (bundle_dir / OUTPUTS / "_export_warnings.txt").is_file()
    assert (bundle_dir / SCRIPT / SCRIPT_HASH_FILE).is_file()

    manifest = json.loads((bundle_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["year"] == 2026
    assert manifest["generated_at"] == "2026-04-01T12:00:00"
    assert "PLTR.pdf" in manifest["files_written"][OUTPUTS]
    assert "alpha_portfolio_new.csv" in manifest["files_written"][NORMALIZED_CSV]
    assert "tax_methods.toml" in manifest["files_written"][CONFIG]
    assert "broker_a.pdf" in manifest["files_written"][ORIGINAL_BROKER_EXPORTS]


@pytest.mark.integration
def test_run_skips_optional_dirs_when_missing(tmp_path: Path, csv_writer):
    input_dir = tmp_path / "csv"
    output_dir = tmp_path / "out"
    bundle_root = tmp_path / "bundles"
    tax_methods_file = tmp_path / "tax_methods.toml"

    csv_writer(
        input_dir / "alpha_portfolio_new.csv",
        [
            {"Symbol": "PLTR", "Trade Date": "20210510", "Purchase Price": "18.76", "Quantity": "10", "Transaction Type": "BUY"},
            {"Symbol": "PLTR", "Trade Date": "20250929", "Purchase Price": "180.00", "Quantity": "10", "Transaction Type": "SELL"},
        ],
    )
    tax_methods_file.write_text(
        'current_year = 2026\n'
        'fx_mode = "annual"\n'
        '\n'
        '[fx_annual_rates]\n'
        '2021 = 21\n'
        '2025 = 24\n'
        '\n'
        '[PLTR]\n'
        '2021 = "FIFO"\n'
        '2025 = "FIFO"\n',
        encoding="utf-8",
    )

    result = run_pipeline(
        input_dir=input_dir,
        output_dir=output_dir,
        tax_methods_file=tax_methods_file,
        generated_at=datetime(2026, 4, 1, 12, 0, 0),
        bundle_root=bundle_root,
        notes_dir=None,
        broker_exports_dir=None,
    )

    bundle_dir = result.bundle_dir
    assert bundle_dir is not None
    assert not (bundle_dir / ORIGINAL_BROKER_EXPORTS).exists()
    assert not (bundle_dir / NOTES).exists()
    assert (bundle_dir / OUTPUTS / "PLTR.pdf").is_file()
