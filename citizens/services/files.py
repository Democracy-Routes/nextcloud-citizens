# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audio inventory, deletion and portable session export (Files tab).

Deleting audio is deliberately narrow: the audio bytes go, the recording row,
its transcript, findings and the report stay. That is what makes it usable both
as a manual cleanup and (next round) as an automatic retention policy.
"""

import json
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import Assembly, Participant, Recording, Transcript
from citizens.db.models.base import utcnow
from citizens.db.models.findings import Finding, FindingEvidence
from citizens.db.models.recording import AudioChunk
from citizens.logging_setup import get_logger
from citizens.services.recording_states import InvalidTransition, transition
from citizens.services.report import build_report, render_markdown
from citizens.services.transcription import transcript_payload
from citizens.storage.paths import (
    exports_dir,
    live_caption_path,
    purge_assembly_exports,
    recording_dir,
)

log = get_logger(__name__)

EXPORT_FORMAT_VERSION = 1


def _storage_root() -> Path:
    return get_settings().app_persistent_storage


def canonical_path(recording: Recording) -> Path | None:
    if not recording.canonical_audio_path:
        return None
    path = _storage_root() / recording.canonical_audio_path
    return path if path.is_file() else None


def audio_filename(assembly: Assembly, recording: Recording, position: int) -> str:
    stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in assembly.name)[:40].strip("-")
    suffix = Path(recording.canonical_audio_path or "audio.webm").suffix or ".webm"
    return f"{stem or 'assembly'}-round{position}-table{recording.table_number}{suffix}"


def list_files(session: Session, assembly: Assembly) -> dict:
    """Per-round, per-table audio inventory with on-disk sizes."""
    recordings = list(
        session.execute(
            select(Recording)
            .where(Recording.assembly_id == assembly.id)
            .order_by(Recording.table_number, Recording.created_at)
        ).scalars()
    )
    # source too, so the tab can mark a captions-derived transcript and offer
    # to replace it with a real one
    transcribed = {
        recording_id: source
        for recording_id, source in session.execute(
            select(Transcript.recording_id, Transcript.source).where(
                Transcript.recording_id.in_([r.id for r in recordings] or [""])
            )
        )
    }
    by_round: dict[str, list[dict]] = {}
    total_bytes = 0
    deleted_count = 0
    for recording in recordings:
        path = canonical_path(recording)
        size = path.stat().st_size if path else 0
        chunk_bytes = (
            session.execute(
                select(AudioChunk.size_bytes).where(AudioChunk.recording_id == recording.id)
            ).scalars()
            if recording.audio_deleted_at is None
            else []
        )
        size += sum(chunk_bytes)
        total_bytes += size
        if recording.audio_deleted_at is not None:
            deleted_count += 1
        by_round.setdefault(recording.round_id, []).append(
            {
                "recording_id": recording.id,
                "table_number": recording.table_number,
                "state": recording.state,
                "mime_type": recording.mime_type,
                "duration_seconds": recording.duration_seconds,
                "size_bytes": size,
                "sha256": recording.sha256,
                "created_at": recording.created_at.isoformat() if recording.created_at else None,
                "audio_available": path is not None,
                "audio_deleted_at": (
                    recording.audio_deleted_at.isoformat() if recording.audio_deleted_at else None
                ),
                "has_transcript": recording.id in transcribed,
                "transcript_source": transcribed.get(recording.id, ""),
                "can_retranscribe": path is not None,
            }
        )
    return {
        "totals": {
            "recordings": len(recordings),
            "audio_bytes": total_bytes,
            "audio_deleted": deleted_count,
        },
        "rounds": [
            {
                "id": round_.id,
                "position": round_.position,
                "title": round_.title,
                "tables": sorted(
                    by_round.get(round_.id, []), key=lambda row: row["table_number"]
                ),
            }
            for round_ in assembly.rounds
        ],
    }


def delete_recording_audio(session: Session, recording: Recording) -> int:
    """Remove the audio bytes of one recording; keep everything derived.

    Callers must not invoke this while an ASSEMBLE_AUDIO job is live for the
    recording — see _refuse_if_being_assembled in citizens/api/files.py. A
    transcription already in flight is a different matter and deliberately
    allowed: the organizer asked for the audio to go, and the transcript that
    lands afterwards is an honest record of what was said.
    """
    root = _storage_root()
    freed = 0
    path = canonical_path(recording)
    if path is not None:
        freed += path.stat().st_size
        path.unlink(missing_ok=True)
    for chunk in session.execute(
        select(AudioChunk).where(AudioChunk.recording_id == recording.id)
    ).scalars():
        chunk_path = root / chunk.path
        if chunk_path.is_file():
            freed += chunk.size_bytes
            chunk_path.unlink(missing_ok=True)
        session.delete(chunk)
    directory = recording_dir(
        root, recording.assembly_id, recording.round_id, recording.table_id, recording.id
    )
    chunks_dir = directory / "chunks"
    if chunks_dir.is_dir():
        try:
            chunks_dir.rmdir()  # empty by now; keep manifest.json as the audit trail
        except OSError:
            pass
    recording.received_chunks = 0
    recording.audio_deleted_at = utcnow()
    # Any export archive of this assembly still contains this audio in full.
    # Leaving them is the difference between the retention sweep reporting the
    # audio deleted and the audio actually being gone.
    freed += purge_assembly_exports(root, recording.assembly_id)
    log.info("recording_audio_deleted", recording_id=recording.id, freed_bytes=freed)
    return freed


def mark_evidence_removed(session: Session, transcript: Transcript) -> int:
    """Flag findings that quote this transcript before its segments disappear.

    FindingEvidence rows cascade away with the segments (SQLite ON DELETE
    CASCADE), so without this marker a report would quietly render findings
    with no quotes and no explanation."""
    segment_ids = [segment.id for segment in transcript.segments]
    if not segment_ids:
        return 0
    finding_ids = list(
        session.execute(
            select(FindingEvidence.finding_id).where(
                FindingEvidence.transcript_segment_id.in_(segment_ids)
            )
        ).scalars()
    )
    if not finding_ids:
        return 0
    now = utcnow()
    findings = list(
        session.execute(select(Finding).where(Finding.id.in_(finding_ids))).scalars()
    )
    for finding in findings:
        finding.evidence_removed_at = now
    return len(findings)


def delete_recording_transcript(session: Session, recording: Recording) -> bool:
    """Erase the verbatim text of one recording: transcript rows, the raw
    provider JSON, and the quotes inside findings. The findings and the AI
    summaries survive; the audio (if still present) can be transcribed again."""
    transcript = session.execute(
        select(Transcript).where(Transcript.recording_id == recording.id)
    ).scalar_one_or_none()
    if transcript is None:
        return False
    marked = mark_evidence_removed(session, transcript)
    if transcript.raw_response_path:
        (_storage_root() / transcript.raw_response_path).unlink(missing_ok=True)
    # the captions this may have been built from are the same speech in another
    # file; "erase the verbatim text" has to mean both
    live_caption_path(_storage_root(), recording.assembly_id, recording.id).unlink(
        missing_ok=True
    )
    session.delete(transcript)
    session.flush()
    # back to plain audio so the organizer can re-run transcription
    if canonical_path(recording) is not None and recording.state != "AUDIO_READY":
        try:
            transition(recording, "AUDIO_READY")
        except InvalidTransition:
            log.warning(
                "transcript_deleted_state_kept",
                recording_id=recording.id,
                state=recording.state,
            )
    log.info("recording_transcript_deleted", recording_id=recording.id, findings_marked=marked)
    return True


def delete_assembly_transcripts(session: Session, assembly: Assembly) -> int:
    count = 0
    for recording in _recordings(session, assembly):
        if delete_recording_transcript(session, recording):
            count += 1
    return count


def refresh_frozen_report(session: Session, assembly: Assembly) -> None:
    """Deleted data must also leave the frozen copy participants read."""
    if not assembly.final_report_json:
        return
    from citizens.services.lifecycle import snapshot_final_report

    snapshot_final_report(session, assembly)
    log.info("final_report_resnapshotted", assembly_id=assembly.id)


def delete_assembly_audio(session: Session, assembly: Assembly) -> tuple[int, int]:
    freed = 0
    count = 0
    for recording in session.execute(
        select(Recording).where(Recording.assembly_id == assembly.id)
    ).scalars():
        if recording.audio_deleted_at is not None and canonical_path(recording) is None:
            continue
        freed += delete_recording_audio(session, recording)
        count += 1
    # Unconditionally, not only via the loop above: an assembly whose
    # recordings were all deleted individually still has export archives, and
    # the loop skips every one of those recordings. This is the path the
    # retention sweep takes, so missing it meant reporting the audio purged
    # while a complete copy of it remained on disk.
    freed += purge_assembly_exports(_storage_root(), assembly.id)
    return count, freed


def build_audio_zip(session: Session, assembly: Assembly) -> Path:
    """Every table's canonical audio in one archive."""
    target = _export_target(assembly, "audio")
    positions = {round_.id: round_.position for round_ in assembly.rounds}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as archive:
        for recording in _recordings(session, assembly):
            path = canonical_path(recording)
            if path is None:
                continue
            archive.write(path, audio_filename(assembly, recording, positions.get(recording.round_id, 0)))
    return target


def build_session_export(session: Session, assembly: Assembly) -> Path:
    """Portable archive of the whole session: metadata, audio, transcripts,
    findings and the report — enough to move it to another server."""
    from citizens.services.branding import logo_path, organization_name
    from citizens.services.report_pdf import render_pdf

    target = _export_target(assembly, "session")
    positions = {round_.id: round_.position for round_ in assembly.rounds}
    recordings = _recordings(session, assembly)
    report = build_report(session, assembly, include_drafts=True)

    manifest = {
        "format_version": EXPORT_FORMAT_VERSION,
        "exported_at": utcnow().isoformat(),
        "assembly": {
            "id": assembly.id,
            "name": assembly.name,
            "description": assembly.description,
            "language": assembly.language,
            "status": assembly.status,
            "recording_mode": assembly.recording_mode,
            "expected_participants": assembly.expected_participants,
            "default_table_count": assembly.default_table_count,
            "analysis_instructions": assembly.analysis_instructions,
            "created_at": assembly.created_at.isoformat() if assembly.created_at else None,
            "closed_at": assembly.closed_at.isoformat() if assembly.closed_at else None,
        },
        "rounds": [
            {
                "id": round_.id,
                "position": round_.position,
                "title": round_.title,
                "question": round_.question,
                "duration_minutes": round_.duration_minutes,
                "status": round_.status,
                "analysis_summary": round_.analysis_summary,
                "tables": [
                    {"id": table.id, "number": table.number, "label": table.label}
                    for table in round_.tables
                ],
            }
            for round_ in assembly.rounds
        ],
        "participants": [
            {"id": p.id, "label": p.label, "name": p.name, "notes": p.notes}
            for p in session.execute(
                select(Participant).where(Participant.assembly_id == assembly.id)
            ).scalars()
        ],
        "recordings": [
            {
                "id": r.id,
                "round_id": r.round_id,
                "table_number": r.table_number,
                "state": r.state,
                "mime_type": r.mime_type,
                "duration_seconds": r.duration_seconds,
                "sha256": r.sha256,
                "analysis_summary": r.analysis_summary,
                "audio_file": (
                    f"audio/{audio_filename(assembly, r, positions.get(r.round_id, 0))}"
                    if canonical_path(r)
                    else None
                ),
                "audio_deleted_at": r.audio_deleted_at.isoformat() if r.audio_deleted_at else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            }
            for r in recordings
        ],
    }

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=1))
        archive.writestr("README.txt", _README)
        archive.writestr("report.json", json.dumps(report, indent=1))
        archive.writestr("report.md", render_markdown(report))
        try:
            archive.writestr("report.pdf", render_pdf(report, logo_path(), organization_name()))
        except Exception:  # a broken font/logo must not sink the export
            log.warning("export_pdf_failed", assembly_id=assembly.id, exc_info=True)
        for recording in recordings:
            path = canonical_path(recording)
            if path is not None:
                archive.write(
                    path,
                    f"audio/{audio_filename(assembly, recording, positions.get(recording.round_id, 0))}",
                )
            transcript = session.execute(
                select(Transcript).where(Transcript.recording_id == recording.id)
            ).scalar_one_or_none()
            if transcript is not None:
                archive.writestr(
                    f"transcripts/{recording.id}.json",
                    json.dumps(transcript_payload(transcript), indent=1),
                )
                raw = transcript.raw_response_path
                raw_path = _storage_root() / raw if raw else None
                if raw_path is not None and raw_path.is_file():
                    archive.write(raw_path, f"transcripts/{recording.id}.raw.json")
    return target


def _recordings(session: Session, assembly: Assembly) -> list[Recording]:
    return list(
        session.execute(
            select(Recording)
            .where(Recording.assembly_id == assembly.id)
            .order_by(Recording.table_number, Recording.created_at)
        ).scalars()
    )


def _export_target(assembly: Assembly, kind: str) -> Path:
    directory = exports_dir(_storage_root(), assembly.id)
    directory.mkdir(parents=True, exist_ok=True)
    # Drop any earlier archive of the same kind. Each is a throwaway build
    # artifact meant to be streamed and unlinked, but the unlink runs in a
    # background task that never fires if the client disconnects mid-download —
    # so on a venue connection they accumulated, each one a full copy.
    for stale in directory.glob(f"{kind}-*.zip"):
        stale.unlink(missing_ok=True)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    return directory / f"{kind}-{stamp}.zip"


_README = """Nextcloud Citizens — session export
===================================

manifest.json   assembly, rounds, tables, participants and recording metadata
                (format_version tells an importer how to read this archive)
audio/          one canonical audio file per table and round, named
                <assembly>-round<N>-table<M>.<ext>; missing when the audio was
                deleted (see audio_deleted_at in the manifest)
transcripts/    <recording_id>.json   normalized transcript (speakers, segments)
                <recording_id>.raw.json  raw provider response, when available
report.json     the full report structure, including unreviewed drafts
report.md       the same report as Markdown
report.pdf      the formatted report

Checksums: every recording in the manifest carries the SHA-256 of its canonical
audio file, so an import can verify the audio it receives.
"""
