from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from stock_tax_report.analysis.ticker_analysis import analyze_ticker
from stock_tax_report.bundle.assembler import assemble_bundle
from stock_tax_report.bundle.layout import (
    CONFIG,
    FX,
    NORMALIZED_CSV,
    NOTES,
    ORIGINAL_BROKER_EXPORTS,
    OUTPUTS,
)
from stock_tax_report.bundle.methodology import render_methodology_readme
from stock_tax_report.bundle.provenance import compute_package_hash
from stock_tax_report.domain.analysis import TickerAnalysis
from stock_tax_report.domain.bundle import (
    OutputArtifact,
    ReportBundleManifest,
    ReportBundleSpec,
    SourceEvidenceFile,
)
from stock_tax_report.domain.transactions import Transaction
from stock_tax_report.io.csv_discovery import discover_csv_files
from stock_tax_report.io.csv_parser import (
    extract_transactions_from_file,
    group_by_ticker,
)
from stock_tax_report.io.fx_loader import load_fx_rate_book
from stock_tax_report.io.tax_config_loader import (
    load_tax_config,
    validate_tax_config,
)
from stock_tax_report.render.cleanup import _clear_previous_exports
from stock_tax_report.render.pdf_all_tickers import build_all_tickers_year_summary_pdf
from stock_tax_report.render.pdf_ticker import build_pdf_for_ticker
from stock_tax_report.render.summary_csv import write_summary
from stock_tax_report.render.warnings_txt import write_warnings


PACKAGE_ROOT = Path(__file__).resolve().parent


@dataclass
class PipelineResult:
    csv_files_read: int
    transactions_parsed: int
    tickers: int
    pdfs_created: int
    ignored_current_year_sells: int
    output_dir: Path
    pdf_paths: List[Path]
    summary_csv_path: Path
    warnings_txt_path: Path
    all_tickers_pdf_path: Path
    bundle_manifest: Optional[ReportBundleManifest] = None
    bundle_dir: Optional[Path] = None


def _broker_evidence(broker_exports_dir: Path) -> List[SourceEvidenceFile]:
    files: List[SourceEvidenceFile] = []
    for path in sorted(broker_exports_dir.iterdir()):
        if not path.is_file():
            continue
        kind = "broker_pdf" if path.suffix.lower() == ".pdf" else "broker_csv"
        files.append(
            SourceEvidenceFile(
                kind=kind,
                source_path=path,
                dest_subdir=ORIGINAL_BROKER_EXPORTS,
                dest_name=path.name,
            )
        )
    return files


def _normalized_csv_evidence(csv_files: List[Path]) -> List[SourceEvidenceFile]:
    return [
        SourceEvidenceFile(
            kind="normalized_csv",
            source_path=path,
            dest_subdir=NORMALIZED_CSV,
            dest_name=path.name,
        )
        for path in csv_files
    ]


def _fx_evidence(daily_file: Optional[Path]) -> List[SourceEvidenceFile]:
    if daily_file is None:
        return []
    fx_dir = daily_file.parent
    return [
        SourceEvidenceFile(
            kind="fx_daily",
            source_path=path,
            dest_subdir=FX,
            dest_name=path.name,
        )
        for path in sorted(fx_dir.glob("cnb_*.txt"))
        if path.is_file()
    ]


def _notes_evidence(notes_dir: Path) -> List[SourceEvidenceFile]:
    files: List[SourceEvidenceFile] = []
    for path in sorted(notes_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(notes_dir)
        if rel.parent == Path("."):
            dest_subdir = NOTES
        else:
            dest_subdir = (Path(NOTES) / rel.parent).as_posix()
        files.append(
            SourceEvidenceFile(
                kind="note",
                source_path=path,
                dest_subdir=dest_subdir,
                dest_name=path.name,
            )
        )
    return files


def _output_artifacts(output_dir: Path) -> List[OutputArtifact]:
    artifacts: List[OutputArtifact] = []
    for path in sorted(output_dir.iterdir()):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            kind = "pdf"
        elif suffix == ".csv":
            kind = "csv"
        else:
            kind = "txt"
        artifacts.append(
            OutputArtifact(
                kind=kind,
                source_path=path,
                dest_subdir=OUTPUTS,
                dest_name=path.name,
            )
        )
    return artifacts


def run(
    *,
    input_dir: Path,
    output_dir: Path,
    tax_methods_file: Path,
    generated_at: datetime,
    bundle_root: Optional[Path] = None,
    notes_dir: Optional[Path] = None,
    broker_exports_dir: Optional[Path] = None,
) -> PipelineResult:
    csv_files = discover_csv_files(input_dir)

    transactions: List[Transaction] = []
    warnings: List[str] = []
    mapping_notes: List[str] = []
    for csv_file in csv_files:
        result = extract_transactions_from_file(csv_file)
        transactions.extend(result.transactions)
        warnings.extend(result.warnings)
        mapping_notes.extend(result.mapping_notes)

    grouped = group_by_ticker(transactions)

    config = load_tax_config(tax_methods_file)
    fx_rate_book = load_fx_rate_book(config.fx_config)

    validation_errors = validate_tax_config(grouped, config)
    if validation_errors:
        message = "Tax methods validation failed:\n" + "\n".join(
            f"- {e}" for e in validation_errors
        )
        raise ValueError(message)

    analyses: List[TickerAnalysis] = []
    for ticker, txs in grouped.items():
        analyses.append(analyze_ticker(ticker, txs, config))

    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_previous_exports(output_dir)

    pdf_paths: List[Path] = []
    for analysis in analyses:
        pdf_paths.append(
            build_pdf_for_ticker(
                analysis, output_dir, generated_at, config.current_year, fx_rate_book
            )
        )
    all_tickers_pdf = build_all_tickers_year_summary_pdf(
        analyses, output_dir, generated_at, config.current_year, fx_rate_book
    )
    summary_csv_path = write_summary(output_dir, analyses, fx_rate_book)
    warnings_txt_path = write_warnings(
        output_dir, warnings, mapping_notes, analyses, generated_at
    )

    bundle_manifest: Optional[ReportBundleManifest] = None
    bundle_dir: Optional[Path] = None
    if bundle_root is not None:
        package_hash = compute_package_hash(PACKAGE_ROOT)
        readme = render_methodology_readme(config, config.current_year, package_hash)

        source_evidence: List[SourceEvidenceFile] = []
        if broker_exports_dir is not None and broker_exports_dir.is_dir():
            source_evidence.extend(_broker_evidence(broker_exports_dir))
        source_evidence.extend(_normalized_csv_evidence(csv_files))
        source_evidence.append(
            SourceEvidenceFile(
                kind="tax_config",
                source_path=tax_methods_file,
                dest_subdir=CONFIG,
                dest_name=tax_methods_file.name,
            )
        )
        source_evidence.extend(_fx_evidence(config.fx_config.daily_file))
        if notes_dir is not None and notes_dir.is_dir():
            source_evidence.extend(_notes_evidence(notes_dir))

        spec = ReportBundleSpec(
            year=config.current_year,
            output_artifacts=_output_artifacts(output_dir),
            source_evidence=source_evidence,
            methodology_readme=readme,
            package_hash=package_hash,
        )
        bundle_dir = bundle_root / f"tax_{config.current_year}"
        bundle_manifest = assemble_bundle(spec, bundle_dir, generated_at)

    return PipelineResult(
        csv_files_read=len(csv_files),
        transactions_parsed=len(transactions),
        tickers=len(analyses),
        pdfs_created=len(pdf_paths),
        ignored_current_year_sells=sum(
            len(a.ignored_current_year_sells) for a in analyses
        ),
        output_dir=output_dir,
        pdf_paths=pdf_paths,
        summary_csv_path=summary_csv_path,
        warnings_txt_path=warnings_txt_path,
        all_tickers_pdf_path=all_tickers_pdf,
        bundle_manifest=bundle_manifest,
        bundle_dir=bundle_dir,
    )
