from __future__ import annotations

from pathlib import Path

import pytest

from stock_tax_report.bundle.provenance import compute_package_hash


@pytest.mark.unit
def test_compute_package_hash_is_deterministic_and_64_hex(tmp_path: Path):
    pkg = tmp_path / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "a.py").write_text("print('a')\n", encoding="utf-8")
    (pkg / "sub" / "b.py").write_text("print('b')\n", encoding="utf-8")

    first = compute_package_hash(pkg)
    second = compute_package_hash(pkg)
    assert first == second
    assert len(first) == 64
    assert all(c in "0123456789abcdef" for c in first)


@pytest.mark.unit
def test_hash_changes_with_content(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("v1\n", encoding="utf-8")
    h1 = compute_package_hash(pkg)
    (pkg / "a.py").write_text("v2\n", encoding="utf-8")
    h2 = compute_package_hash(pkg)
    assert h1 != h2


@pytest.mark.unit
def test_hash_changes_when_file_renamed(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("body\n", encoding="utf-8")
    h1 = compute_package_hash(pkg)
    (pkg / "a.py").rename(pkg / "b.py")
    h2 = compute_package_hash(pkg)
    assert h1 != h2


@pytest.mark.unit
def test_hash_ignores_non_python_files(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("body\n", encoding="utf-8")
    h1 = compute_package_hash(pkg)
    (pkg / "README.md").write_text("ignored\n", encoding="utf-8")
    h2 = compute_package_hash(pkg)
    assert h1 == h2


@pytest.mark.unit
def test_hash_raises_for_missing_root(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        compute_package_hash(tmp_path / "missing")
