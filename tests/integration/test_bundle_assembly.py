from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from stock_tax_report.bundle.assembler import assemble_bundle
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
from stock_tax_report.bundle.methodology import render_methodology_readme
from stock_tax_report.bundle.provenance import compute_package_hash
from stock_tax_report.domain.bundle import (
    OutputArtifact,
    ReportBundleSpec,
    SourceEvidenceFile,
)
from stock_tax_report.domain.config import TaxConfig
from stock_tax_report.domain.fx import FxConfig


@pytest.fixture
def fake_run_tree(tmp_path: Path) -> dict[str, Path]:
    sources = tmp_path / "sources"
    outputs = tmp_path / "outputs"
    bundle = tmp_path / "bundle"

    (sources / "brokers").mkdir(parents=True)
    (sources / "csv").mkdir(parents=True)
    (sources / "fx").mkdir(parents=True)
    (sources / "notes").mkdir(parents=True)
    outputs.mkdir(parents=True)

    (sources / "brokers" / "broker_a.pdf").write_bytes(b"%PDF-1.4 fake A\n")
    (sources / "brokers" / "broker_b.pdf").write_bytes(b"%PDF-1.4 fake B\n")
    (sources / "csv" / "broker_a.csv").write_text("Symbol,Quantity\nAAA,1\n", encoding="utf-8")
    (sources / "csv" / "broker_b.csv").write_text("Symbol,Quantity\nBBB,2\n", encoding="utf-8")
    (sources / "fx" / "cnb_2025.txt").write_text("Datum|Kurz\n01.01.2025|24.0\n", encoding="utf-8")
    (sources / "tax_methods.toml").write_text(
        'current_year = 2026\nfx_mode = "annual"\n[fx_annual_rates]\n2025 = 25\n[AAA]\n2025 = "FIFO"\n',
        encoding="utf-8",
    )
    (sources / "notes" / "audit.md").write_text("# Audit notes\nLooks good.\n", encoding="utf-8")

    (outputs / "AAA.pdf").write_bytes(b"%PDF fake AAA\n")
    (outputs / "_export_summary.csv").write_text("ticker\nAAA\n", encoding="utf-8")
    (outputs / "_export_warnings.txt").write_text("None\n", encoding="utf-8")

    return {"sources": sources, "outputs": outputs, "bundle": bundle}


def test_assemble_bundle_creates_full_layout(fake_run_tree):
    sources = fake_run_tree["sources"]
    outputs = fake_run_tree["outputs"]
    bundle = fake_run_tree["bundle"]

    config = TaxConfig(
        current_year=2026,
        methods_by_ticker={"AAA": {2025: "fifo"}},
        fx_config=FxConfig(mode="annual", annual_rates={2025: Decimal("25")}),
    )
    package_hash = "x" * 64
    readme = render_methodology_readme(config, year=2025, package_hash=package_hash)

    spec = ReportBundleSpec(
        year=2025,
        methodology_readme=readme,
        package_hash=package_hash,
        source_evidence=[
            SourceEvidenceFile("broker_pdf", sources / "brokers" / "broker_a.pdf", ORIGINAL_BROKER_EXPORTS, "broker_a.pdf"),
            SourceEvidenceFile("broker_pdf", sources / "brokers" / "broker_b.pdf", ORIGINAL_BROKER_EXPORTS, "broker_b.pdf"),
            SourceEvidenceFile("normalized_csv", sources / "csv" / "broker_a.csv", NORMALIZED_CSV, "broker_a.csv"),
            SourceEvidenceFile("normalized_csv", sources / "csv" / "broker_b.csv", NORMALIZED_CSV, "broker_b.csv"),
            SourceEvidenceFile("tax_config", sources / "tax_methods.toml", CONFIG, "tax_methods.toml"),
            SourceEvidenceFile("fx_daily", sources / "fx" / "cnb_2025.txt", FX, "cnb_2025.txt"),
            SourceEvidenceFile("note", sources / "notes" / "audit.md", NOTES, "audit.md"),
        ],
        output_artifacts=[
            OutputArtifact("pdf", outputs / "AAA.pdf", OUTPUTS, "AAA.pdf"),
            OutputArtifact("csv", outputs / "_export_summary.csv", OUTPUTS, "_export_summary.csv"),
            OutputArtifact("txt", outputs / "_export_warnings.txt", OUTPUTS, "_export_warnings.txt"),
        ],
    )

    generated_at = datetime(2026, 4, 1, 12, 0, 0)
    manifest = assemble_bundle(spec, bundle, generated_at)

    assert (bundle / README_METHODOLOGY).is_file()
    assert (bundle / ORIGINAL_BROKER_EXPORTS / "broker_a.pdf").is_file()
    assert (bundle / ORIGINAL_BROKER_EXPORTS / "broker_b.pdf").is_file()
    assert (bundle / NORMALIZED_CSV / "broker_a.csv").is_file()
    assert (bundle / NORMALIZED_CSV / "broker_b.csv").is_file()
    assert (bundle / CONFIG / "tax_methods.toml").is_file()
    assert (bundle / FX / "cnb_2025.txt").is_file()
    assert (bundle / NOTES / "audit.md").is_file()
    assert (bundle / OUTPUTS / "AAA.pdf").is_file()
    assert (bundle / OUTPUTS / "_export_summary.csv").is_file()
    assert (bundle / OUTPUTS / "_export_warnings.txt").is_file()
    assert (bundle / SCRIPT / SCRIPT_HASH_FILE).read_text(encoding="utf-8").strip() == package_hash

    manifest_data = json.loads((bundle / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest_data["year"] == 2025
    assert manifest_data["package_hash"] == package_hash
    assert manifest_data["generated_at"] == "2026-04-01T12:00:00"
    assert manifest_data["files_written"][ORIGINAL_BROKER_EXPORTS] == ["broker_a.pdf", "broker_b.pdf"]
    assert manifest_data["files_written"][OUTPUTS] == [
        "AAA.pdf",
        "_export_summary.csv",
        "_export_warnings.txt",
    ]
    assert manifest_data["files_written"][SCRIPT] == [SCRIPT_HASH_FILE]
    assert manifest.year == 2025


def test_assemble_bundle_raises_for_missing_source(tmp_path: Path):
    bundle = tmp_path / "bundle"
    spec = ReportBundleSpec(
        year=2025,
        methodology_readme="readme",
        package_hash="abc",
        source_evidence=[
            SourceEvidenceFile("note", tmp_path / "missing.md", NOTES, "missing.md"),
        ],
        output_artifacts=[],
    )
    with pytest.raises(FileNotFoundError):
        assemble_bundle(spec, bundle, datetime(2026, 1, 1))


def test_compute_package_hash_is_deterministic(tmp_path: Path):
    pkg = tmp_path / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "a.py").write_text("print('a')\n", encoding="utf-8")
    (pkg / "sub" / "b.py").write_text("print('b')\n", encoding="utf-8")

    first = compute_package_hash(pkg)
    second = compute_package_hash(pkg)
    assert first == second
    assert len(first) == 64

    (pkg / "a.py").write_text("print('a2')\n", encoding="utf-8")
    third = compute_package_hash(pkg)
    assert third != first


def test_methodology_readme_includes_year_and_methods():
    config = TaxConfig(
        current_year=2026,
        methods_by_ticker={"AAA": {2024: "fifo", 2025: "time_test_max"}},
        fx_config=FxConfig(mode="annual", annual_rates={2024: Decimal("23"), 2025: Decimal("25")}),
    )
    readme = render_methodology_readme(config, year=2025, package_hash="deadbeef")
    assert "Year 2025" in readme
    assert "FIFO" in readme
    assert "TIME_TEST_MAX" in readme
    assert "deadbeef" in readme
    assert "| AAA | 2024 | FIFO |" in readme
    assert "| AAA | 2025 | TIME_TEST_MAX |" in readme
