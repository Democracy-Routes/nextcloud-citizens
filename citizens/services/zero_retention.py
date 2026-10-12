# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Zero retention (0.7, S10): an assembly that keeps its report and nothing
else — no audio, no transcript — once it is closed and everything that could
still read them has finished.

What stays: the frozen report (assemblies.final_report_json, quotations
included — it is the record the participants were promised) and a PDF of it
beside the assembly's exports. What goes: every recording's audio, every
transcript (findings lose their quoted evidence rows; the frozen report keeps
the text), the live caption files. The order matters: the exports directory
is wiped with the audio, so the PDF is written after.
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import Assembly, Recording
from citizens.db.models.base import utcnow
from citizens.logging_setup import get_logger
from citizens.services.audit import record_audit_event
from citizens.services.jobs import has_live_job
from citizens.storage.paths import exports_dir

log = get_logger(__name__)

#: states in which a recording is still being made or uploaded: nothing is
#: deleted under it
TRANSIENT_STATES = (
    "CREATED", "RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS", "ASSEMBLING",
    "TRANSCRIBING", "ANALYZING",
)
PROCESSING_JOBS = ("ASSEMBLE_AUDIO", "TRANSCRIBE_FINAL", "TRANSCRIBE_FROM_LIVE", "ANALYZE_TABLE")
ROUND_JOBS = ("ANALYZE_ROUND",)
ASSEMBLY_JOBS = ("ANALYZE_ASSEMBLY",)
PDF_NAME = "final-report.pdf"


def retained_pdf_path(assembly_id: str) -> Path:
    return exports_dir(get_settings().app_persistent_storage, assembly_id) / PDF_NAME


def _still_processing(session: Session, assembly: Assembly) -> str | None:
    """Why it is too early, or None."""
    recordings = list(
        session.execute(select(Recording).where(Recording.assembly_id == assembly.id)).scalars()
    )
    for recording in recordings:
        if recording.state in TRANSIENT_STATES:
            return f"recording {recording.id} is {recording.state}"
        for kind in PROCESSING_JOBS:
            if has_live_job(session, kind, "recording_id", recording.id):
                return f"{kind} live for recording {recording.id}"
    for round_ in assembly.rounds:
        for kind in ROUND_JOBS:
            if has_live_job(session, kind, "round_id", round_.id):
                return f"{kind} live for round {round_.id}"
    for kind in ASSEMBLY_JOBS:
        if has_live_job(session, kind, "assembly_id", assembly.id):
            return f"{kind} live"
    return None


def apply_if_ready(session: Session, assembly: Assembly) -> dict | None:
    """Run zero retention for a closed assembly that asked for it, once,
    when nothing is still reading the audio or the transcripts. Returns what
    was done, or None when it was not (yet) to be done."""
    if (
        not assembly.zero_retention
        or assembly.closed_at is None
        or assembly.zero_retention_done_at is not None
    ):
        return None
    reason = _still_processing(session, assembly)
    if reason is not None:
        log.info("zero_retention_waiting", assembly_id=assembly.id, reason=reason)
        return None
    from citizens.services import files as files_svc
    from citizens.services.branding import logo_path, organization_name
    from citizens.services.lifecycle import snapshot_final_report
    from citizens.services.report_pdf import render_pdf
    from citizens.storage.paths import live_captions_dir

    # the report of record, with everything still readable
    report = snapshot_final_report(session, assembly)
    pdf = render_pdf(report, logo_path(), organization_name())
    deleted, freed, _kept = files_svc.delete_assembly_audio(
        session, assembly, keep_untranscribed=False
    )
    transcripts = files_svc.delete_assembly_transcripts(session, assembly)
    captions = _remove_live_captions(live_captions_dir(get_settings().app_persistent_storage, assembly.id))
    # after the audio: deleting it wipes the exports directory
    target = retained_pdf_path(assembly.id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf)
    assembly.audio_purged_at = assembly.audio_purged_at or utcnow()
    assembly.zero_retention_done_at = utcnow()
    done = {
        "recordings": deleted, "freed_bytes": freed, "transcripts": transcripts,
        "caption_files": captions, "pdf_bytes": len(pdf),
    }
    record_audit_event(session, "zero_retention_applied", "assembly", assembly.id, data=done)
    log.info("zero_retention_applied", assembly_id=assembly.id, **done)
    return done


def _remove_live_captions(directory: Path) -> int:
    import shutil

    if not directory.is_dir():
        return 0
    count = sum(1 for path in directory.rglob("*") if path.is_file())
    shutil.rmtree(directory, ignore_errors=True)
    return count


def sweep() -> int:
    """Closed assemblies that asked for zero retention and were still being
    processed when they closed: run it once the processing is over."""
    from citizens.db.session import session_scope

    applied = 0
    with session_scope() as session:
        pending = list(
            session.execute(
                select(Assembly).where(
                    Assembly.zero_retention.is_(True),
                    Assembly.closed_at.is_not(None),
                    Assembly.zero_retention_done_at.is_(None),
                )
            ).scalars()
        )
        for assembly in pending:
            if apply_if_ready(session, assembly) is not None:
                applied += 1
    return applied
