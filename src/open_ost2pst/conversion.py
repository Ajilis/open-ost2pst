"""High-level conversion orchestration with progress reporting."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from open_ost2pst.pst.bridge import WriteReport, mailbox_to_messaging
from open_ost2pst.reader.pff_reader import (
    ExtractionReport,
    InspectionStats,
    inspect_store,
    load_mailbox,
)
from open_ost2pst.verification import VerificationReport, verify_against_mailbox


@dataclass(frozen=True, slots=True)
class ConversionProgress:
    percent: int
    stage: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ConversionResult:
    source: Path
    destination: Path
    inspection: InspectionStats
    extraction: ExtractionReport
    writing: WriteReport
    verification: VerificationReport

    @property
    def ok(self) -> bool:
        return self.verification.ok

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "destination": str(self.destination),
            "inspection": self.inspection.to_dict(),
            "extraction": self.extraction.to_dict(),
            "writing": self.writing.to_dict(),
            "verification": self.verification.to_dict(),
        }


ProgressCallback = Callable[[ConversionProgress], None]


class ConversionVerificationError(RuntimeError):
    """Raised when the generated PST reopens but does not match its source."""

    def __init__(self, result: ConversionResult) -> None:
        self.result = result
        super().__init__(
            "automatic verification found "
            f"{result.verification.mismatch_count} mismatch(es)"
        )


def convert_file(
    source: str | Path,
    destination: str | Path,
    *,
    report_path: str | Path | None = None,
    overwrite: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> ConversionResult:
    """Convert one OST/PST to PST and report deterministic progress.

    Progress ranges are weighted as follows:
    0-5   preflight/inspection
    5-55  source extraction
    55-80 mailbox-to-PST mapping
    80-90 PST construction/write
    90-100 verification/reporting
    """

    source_path = Path(source)
    destination_path = Path(destination)

    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path.suffix.lower() not in (".ost", ".pst"):
        raise ValueError("source must be an OST or PST file")
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("destination must be different from the source file")
    if destination_path.exists() and not overwrite:
        raise FileExistsError(destination_path)

    destination_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(percent: int, stage: str, detail: str = "") -> None:
        if progress_callback is not None:
            progress_callback(
                ConversionProgress(
                    percent=max(0, min(100, int(percent))),
                    stage=stage,
                    detail=detail,
                )
            )

    emit(0, "Préparation", source_path.name)
    emit(2, "Analyse de la source", "Comptage des éléments")
    inspection = inspect_store(source_path)

    extraction_total = max(
        1,
        inspection.folders + inspection.messages + inspection.attachments,
    )
    emit(
        5,
        "Extraction OST",
        (
            f"{inspection.folders} dossiers, "
            f"{inspection.messages} messages, "
            f"{inspection.attachments} pièces jointes"
        ),
    )

    def extraction_progress(report: ExtractionReport) -> None:
        done = (
            report.folders_loaded
            + report.folders_failed
            + report.messages_loaded
            + report.messages_failed
            + report.attachments_loaded
            + report.attachments_failed
        )
        percent = 5 + min(50, round(50 * done / extraction_total))
        emit(percent, "Extraction OST", f"{min(done, extraction_total)}/{extraction_total}")

    mailbox, extraction = load_mailbox(
        source_path,
        progress_callback=extraction_progress,
    )

    try:
        emit(55, "Extraction terminée", f"{mailbox.message_count} messages")

        write_total = max(
            1,
            (
                mailbox.folder_count
                + mailbox.message_count
                + mailbox.attachment_count
            ),
        )

        def writing_progress(report: WriteReport) -> None:
            done = (
                report.folders_written
                + report.messages_written
                + report.attachments_written
                + report.attachments_failed
            )
            percent = 55 + min(25, round(25 * done / write_total))
            emit(
                percent,
                "Préparation du PST",
                f"{min(done, write_total)}/{write_total}",
            )

        builder, writing = mailbox_to_messaging(
            mailbox,
            progress_callback=writing_progress,
        )

        emit(
            80,
            "Construction et écriture du PST",
            "Streaming NDB/LTP/Messaging vers le disque",
        )
        builder.write(destination_path)

        emit(87, "PST écrit sur disque", destination_path.name)
        emit(92, "Vérification", "Réouverture avec libpff")
        verification = verify_against_mailbox(
            destination_path,
            mailbox,
            source_label=str(source_path),
        )

        result = ConversionResult(
            source=source_path,
            destination=destination_path,
            inspection=inspection,
            extraction=extraction,
            writing=writing,
            verification=verification,
        )

        if report_path is not None:
            emit(97, "Rapport", Path(report_path).name)
            report_target = Path(report_path)
            report_target.parent.mkdir(parents=True, exist_ok=True)
            report_target.write_text(
                json.dumps(
                    result.to_dict(),
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

        if not verification.ok:
            emit(
                100,
                "Vérification échouée",
                f"{verification.mismatch_count} écart(s)",
            )
            raise ConversionVerificationError(result)

        emit(100, "Terminé", destination_path.name)
        return result
    finally:
        mailbox.cleanup()
