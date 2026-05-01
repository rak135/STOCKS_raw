from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal


OutputArtifactKind = Literal["pdf", "csv", "txt"]
SourceEvidenceKind = Literal[
    "broker_csv",
    "broker_pdf",
    "normalized_csv",
    "tax_config",
    "fx_daily",
    "fx_annual",
    "script",
    "note",
]


@dataclass
class OutputArtifact:
    kind: OutputArtifactKind
    source_path: Path
    dest_subdir: str
    dest_name: str


@dataclass
class SourceEvidenceFile:
    kind: SourceEvidenceKind
    source_path: Path
    dest_subdir: str
    dest_name: str


@dataclass
class ReportBundleSpec:
    year: int
    output_artifacts: List[OutputArtifact]
    source_evidence: List[SourceEvidenceFile]
    methodology_readme: str
    package_hash: str


@dataclass
class ReportBundleManifest:
    year: int
    generated_at: datetime
    bundle_root: Path
    package_hash: str
    files_written: Dict[str, List[str]] = field(default_factory=dict)
