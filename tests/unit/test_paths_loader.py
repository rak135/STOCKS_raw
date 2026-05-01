from __future__ import annotations

from pathlib import Path

import pytest

from stock_tax_report.io.paths_loader import DEFAULT_PATHS, load_report_paths


@pytest.mark.unit
def test_load_returns_defaults_when_file_missing(tmp_path):
    paths = load_report_paths(tmp_path / "missing.toml")
    assert paths.normalized_csv_dir == DEFAULT_PATHS.normalized_csv_dir
    assert paths.bundle_root == DEFAULT_PATHS.bundle_root


@pytest.mark.unit
def test_load_returns_defaults_when_file_none():
    paths = load_report_paths(None)
    assert paths.output_dir == DEFAULT_PATHS.output_dir


@pytest.mark.unit
def test_load_overrides_only_specified_keys(tmp_path):
    paths_file = tmp_path / "report_paths.toml"
    paths_file.write_text(
        '[sources]\n'
        'normalized_csv_dir = "C:/data/csv"\n'
        '\n'
        '[bundle]\n'
        'output_root = "C:/data/bundles"\n',
        encoding="utf-8",
    )

    paths = load_report_paths(paths_file)
    assert paths.normalized_csv_dir == Path("C:/data/csv")
    assert paths.bundle_root == Path("C:/data/bundles")
    assert paths.output_dir == DEFAULT_PATHS.output_dir
    assert paths.tax_methods_file == DEFAULT_PATHS.tax_methods_file
    assert paths.notes_dir == DEFAULT_PATHS.notes_dir


@pytest.mark.unit
def test_load_supports_all_optional_overrides(tmp_path):
    paths_file = tmp_path / "report_paths.toml"
    paths_file.write_text(
        '[sources]\n'
        'normalized_csv_dir = "C:/csv"\n'
        'notes_dir = "C:/notes"\n'
        'original_broker_exports_dir = "C:/brokers"\n'
        'tax_methods_file = "C:/tax.toml"\n'
        '\n'
        '[bundle]\n'
        'output_root = "C:/bundles"\n'
        '\n'
        '[outputs]\n'
        'output_dir = "C:/out"\n',
        encoding="utf-8",
    )

    paths = load_report_paths(paths_file)
    assert paths.normalized_csv_dir == Path("C:/csv")
    assert paths.notes_dir == Path("C:/notes")
    assert paths.broker_exports_dir == Path("C:/brokers")
    assert paths.tax_methods_file == Path("C:/tax.toml")
    assert paths.bundle_root == Path("C:/bundles")
    assert paths.output_dir == Path("C:/out")


@pytest.mark.unit
def test_load_rejects_invalid_toml(tmp_path):
    paths_file = tmp_path / "report_paths.toml"
    paths_file.write_text("not = valid = toml", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid TOML"):
        load_report_paths(paths_file)
