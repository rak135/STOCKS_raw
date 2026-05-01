from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ReportPaths:
    normalized_csv_dir: Path
    output_dir: Path
    bundle_root: Path
    tax_methods_file: Path
    notes_dir: Optional[Path] = None
    broker_exports_dir: Optional[Path] = None


REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PATHS = ReportPaths(
    normalized_csv_dir=REPO_ROOT / ".csv",
    output_dir=REPO_ROOT / ".pdf exports tax methods",
    bundle_root=REPO_ROOT / ".tax_bundles",
    tax_methods_file=REPO_ROOT / "tax_methods.toml",
    notes_dir=REPO_ROOT / ".notes",
    broker_exports_dir=REPO_ROOT / ".original_broker_exports",
)


def _path_or_none(raw: object, field: str) -> Optional[Path]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"report_paths.toml: '{field}' must be a string path")
    text = raw.strip()
    return Path(text) if text else None


def load_report_paths(paths_file: Optional[Path]) -> ReportPaths:
    paths = ReportPaths(
        normalized_csv_dir=DEFAULT_PATHS.normalized_csv_dir,
        output_dir=DEFAULT_PATHS.output_dir,
        bundle_root=DEFAULT_PATHS.bundle_root,
        tax_methods_file=DEFAULT_PATHS.tax_methods_file,
        notes_dir=DEFAULT_PATHS.notes_dir,
        broker_exports_dir=DEFAULT_PATHS.broker_exports_dir,
    )
    if paths_file is None or not paths_file.exists():
        return paths

    try:
        data = tomllib.loads(paths_file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"report_paths.toml: invalid TOML ({exc})") from exc

    sources = data.get("sources", {})
    if not isinstance(sources, dict):
        raise ValueError("report_paths.toml: [sources] must be a table")
    bundle = data.get("bundle", {})
    if not isinstance(bundle, dict):
        raise ValueError("report_paths.toml: [bundle] must be a table")
    outputs = data.get("outputs", {})
    if not isinstance(outputs, dict):
        raise ValueError("report_paths.toml: [outputs] must be a table")

    csv_dir = _path_or_none(sources.get("normalized_csv_dir"), "sources.normalized_csv_dir")
    if csv_dir is not None:
        paths.normalized_csv_dir = csv_dir
    notes = _path_or_none(sources.get("notes_dir"), "sources.notes_dir")
    if notes is not None:
        paths.notes_dir = notes
    brokers = _path_or_none(sources.get("original_broker_exports_dir"), "sources.original_broker_exports_dir")
    if brokers is not None:
        paths.broker_exports_dir = brokers
    config_file = _path_or_none(sources.get("tax_methods_file"), "sources.tax_methods_file")
    if config_file is not None:
        paths.tax_methods_file = config_file

    bundle_root = _path_or_none(bundle.get("output_root"), "bundle.output_root")
    if bundle_root is not None:
        paths.bundle_root = bundle_root

    output_dir = _path_or_none(outputs.get("output_dir"), "outputs.output_dir")
    if output_dir is not None:
        paths.output_dir = output_dir

    return paths
