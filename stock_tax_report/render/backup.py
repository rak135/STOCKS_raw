from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable, List


def _backup_dir_name(generated_at: datetime) -> str:
    return f"export_{generated_at.strftime('%Y-%m-%d_%H-%M-%S')}"


def _unique_backup_dir(backup_root: Path, generated_at: datetime) -> Path:
    base = backup_root / _backup_dir_name(generated_at)
    if not base.exists():
        return base

    index = 2
    while True:
        candidate = backup_root / f"{base.name}_{index}"
        if not candidate.exists():
            return candidate
        index += 1


def backup_exported_files(
    output_dir: Path,
    backup_root: Path,
    generated_at: datetime,
) -> Path:
    files = sorted(path for path in output_dir.iterdir() if path.is_file())
    backup_dir = _unique_backup_dir(backup_root, generated_at)
    backup_dir.mkdir(parents=True, exist_ok=False)

    copied: List[str] = []
    for source in files:
        shutil.copy2(source, backup_dir / source.name)
        copied.append(source.name)

    _write_manifest(backup_dir, output_dir, generated_at, copied)
    return backup_dir


def _write_manifest(
    backup_dir: Path,
    output_dir: Path,
    generated_at: datetime,
    copied_files: Iterable[str],
) -> None:
    lines = [
        "Export backup",
        generated_at.strftime("Generated: %Y-%m-%d %H:%M:%S"),
        f"Source output dir: {output_dir}",
        "",
        "Files",
    ]
    lines.extend(copied_files or ["None"])
    (backup_dir / "_backup_manifest.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
