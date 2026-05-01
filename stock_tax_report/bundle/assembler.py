from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from stock_tax_report.bundle.layout import (
    MANIFEST_FILE,
    README_METHODOLOGY,
    SCRIPT,
    SCRIPT_HASH_FILE,
)
from stock_tax_report.domain.bundle import ReportBundleManifest, ReportBundleSpec


def _record_written(files_written: Dict[str, List[str]], dest_subdir: str, dest_name: str) -> None:
    files_written.setdefault(dest_subdir, []).append(dest_name)


def _copy_into(source: Path, target_dir: Path, target_name: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / target_name
    shutil.copy2(source, target)
    return target


def _manifest_to_dict(manifest: ReportBundleManifest) -> dict:
    return {
        "year": manifest.year,
        "generated_at": manifest.generated_at.isoformat(),
        "bundle_root": str(manifest.bundle_root),
        "package_hash": manifest.package_hash,
        "files_written": {
            subdir: sorted(names) for subdir, names in sorted(manifest.files_written.items())
        },
    }


def assemble_bundle(spec: ReportBundleSpec, dest_dir: Path, generated_at: datetime) -> ReportBundleManifest:
    dest_dir.mkdir(parents=True, exist_ok=True)
    files_written: Dict[str, List[str]] = {}

    readme_path = dest_dir / README_METHODOLOGY
    readme_path.write_text(spec.methodology_readme, encoding="utf-8")
    _record_written(files_written, "", README_METHODOLOGY)

    for evidence in spec.source_evidence:
        if not evidence.source_path.exists():
            raise FileNotFoundError(f"Bundle source evidence missing: {evidence.source_path}")
        target_dir = dest_dir / evidence.dest_subdir
        _copy_into(evidence.source_path, target_dir, evidence.dest_name)
        _record_written(files_written, evidence.dest_subdir, evidence.dest_name)

    for artifact in spec.output_artifacts:
        if not artifact.source_path.exists():
            raise FileNotFoundError(f"Bundle output artifact missing: {artifact.source_path}")
        target_dir = dest_dir / artifact.dest_subdir
        _copy_into(artifact.source_path, target_dir, artifact.dest_name)
        _record_written(files_written, artifact.dest_subdir, artifact.dest_name)

    script_dir = dest_dir / SCRIPT
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / SCRIPT_HASH_FILE).write_text(spec.package_hash + "\n", encoding="utf-8")
    _record_written(files_written, SCRIPT, SCRIPT_HASH_FILE)

    manifest = ReportBundleManifest(
        year=spec.year,
        generated_at=generated_at,
        bundle_root=dest_dir,
        package_hash=spec.package_hash,
        files_written=files_written,
    )

    manifest_path = dest_dir / MANIFEST_FILE
    manifest_path.write_text(
        json.dumps(_manifest_to_dict(manifest), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    return manifest
