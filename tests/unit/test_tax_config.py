from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from stock_tax_report.io.tax_config_loader import (
    _infer_template_current_year,
    build_template_text,
    load_tax_config,
    write_template_file,
)


@pytest.mark.unit
def test_load_tax_config_rejects_missing_current_year(tmp_path: Path):
    path = tmp_path / "tax_methods.toml"
    path.write_text('[fx_mode_by_year]\n2024 = "annual"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing top-level 'current_year'"):
        load_tax_config(path)


@pytest.mark.unit
def test_load_tax_config_rejects_legacy_fx_mode(tmp_path: Path):
    path = tmp_path / "tax_methods.toml"
    path.write_text(
        'current_year = 2026\n'
        'fx_mode = "annual"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="'fx_mode' is no longer supported"):
        load_tax_config(path)


@pytest.mark.unit
def test_load_tax_config_rejects_missing_fx_mode_by_year(tmp_path: Path):
    path = tmp_path / "tax_methods.toml"
    path.write_text('current_year = 2026\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing top-level \\[fx_mode_by_year\\] table"):
        load_tax_config(path)


@pytest.mark.unit
def test_load_tax_config_rejects_unknown_fx_mode_value(tmp_path: Path):
    path = tmp_path / "tax_methods.toml"
    path.write_text(
        'current_year = 2026\n'
        '\n'
        '[fx_mode_by_year]\n'
        '2025 = "monthly"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be 'daily' or 'annual'"):
        load_tax_config(path)


@pytest.mark.unit
def test_load_tax_config_rejects_unknown_method(tmp_path: Path):
    path = tmp_path / "tax_methods.toml"
    path.write_text(
        'current_year = 2026\n'
        '\n'
        '[fx_mode_by_year]\n'
        '2024 = "annual"\n'
        '\n'
        '[AAA]\n'
        '2024 = "AVERAGE"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid method"):
        load_tax_config(path)


@pytest.mark.unit
def test_load_tax_config_rejects_invalid_year_key(tmp_path: Path):
    path = tmp_path / "tax_methods.toml"
    path.write_text(
        'current_year = 2026\n'
        '\n'
        '[fx_mode_by_year]\n'
        '2024 = "annual"\n'
        '\n'
        '[AAA]\n'
        'twenty = "FIFO"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid year key"):
        load_tax_config(path)


@pytest.mark.unit
def test_load_tax_config_normalises_method_case(tmp_path: Path):
    path = tmp_path / "tax_methods.toml"
    path.write_text(
        'current_year = 2026\n'
        '\n'
        '[fx_mode_by_year]\n'
        '2024 = "annual"\n'
        '\n'
        '[fx_annual_rates]\n'
        '2024 = "23.28"\n'
        '\n'
        '[AAA]\n'
        '2024 = "Time_Test_Max"\n',
        encoding="utf-8",
    )
    config = load_tax_config(path)
    assert config.methods_by_ticker["AAA"][2024] == "time_test_max"
    assert config.fx_config.annual_rates[2024] == Decimal("23.28")
    assert config.fx_config.mode_by_year == {2024: "annual"}


@pytest.mark.unit
def test_infer_template_current_year_picks_max_year(tx_factory):
    txs = [
        tx_factory(when=date(2023, 1, 1)),
        tx_factory(when=date(2025, 5, 1)),
        tx_factory(when=date(2024, 6, 1)),
    ]
    assert _infer_template_current_year(txs) == 2025


@pytest.mark.unit
def test_build_template_text_lists_only_past_years_per_ticker(tx_factory):
    grouped = {
        "AAA": [tx_factory(ticker="AAA", when=date(2023, 1, 1)),
                tx_factory(ticker="AAA", when=date(2025, 1, 1))],
        "BBB": [tx_factory(ticker="BBB", when=date(2025, 1, 1))],
    }
    text = build_template_text(grouped, current_year=2025)
    assert "current_year = 2025" in text
    assert "[fx_mode_by_year]" in text
    assert '2023 = "annual"' in text
    assert "[fx_annual_rates]" in text
    assert "[AAA]" in text
    assert "2023 = \"\"" in text
    # BBB's only year equals current_year so the section is empty (skipped)
    assert "[BBB]" not in text


@pytest.mark.unit
def test_write_template_file_creates_parent_dirs(tmp_path: Path, tx_factory):
    target = tmp_path / "nested" / "tax_methods.toml"
    grouped = {"AAA": [tx_factory(ticker="AAA", when=date(2023, 1, 1))]}
    written = write_template_file(target, grouped, current_year=2025)
    assert written == target
    assert target.exists()
