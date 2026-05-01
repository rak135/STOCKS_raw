from __future__ import annotations

import hashlib
from pathlib import Path


def compute_package_hash(package_root: Path) -> str:
    if not package_root.exists() or not package_root.is_dir():
        raise FileNotFoundError(f"Package root does not exist: {package_root}")

    files = sorted(
        (path for path in package_root.rglob("*.py") if path.is_file()),
        key=lambda p: p.relative_to(package_root).as_posix(),
    )

    hasher = hashlib.sha256()
    for file_path in files:
        relpath = file_path.relative_to(package_root).as_posix()
        hasher.update(relpath.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(file_path.read_bytes())
        hasher.update(b"\0")

    return hasher.hexdigest()
