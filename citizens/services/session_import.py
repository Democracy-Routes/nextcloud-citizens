# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Putting finished material back into the pipeline.

Two things the live pipeline could not take until 0.9: a whole session
exported from this or another server (`files.build_session_export`, format
1 or 2), and a transcript or an audio file made elsewhere for a recording
whose own chunks failed. Both land exactly where the live path would have
put them — a Recording with a Transcript, or with canonical audio — so
transcription, table analysis, round clustering and the report run as after
a live session. Findings, summaries and the report inside an archive are
never copied: the analysis runs again here, with this server's provider and
the assembly's own instructions, and the organizer reviews the result.

Disk work and database work are separate steps on purpose. `stage_archive`
and `prepare_audio` unzip, checksum, probe and remux with no session open;
`import_session` and `attach_audio` then only write rows and rename files
that are already on the storage disk. A request that held SQLite's single
writer slot across an ffmpeg run would queue every phone's chunk upload
behind it (api/files.py has the same rule for exports).
"""

import hashlib
import json
import os
import shutil
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import Assembly, Participant, Recording, Round, Table
from citizens.db.models.base import utcnow
from citizens.domain.tables import color_for
from citizens.logging_setup import get_logger
from citizens.providers.transcription.base import (
    NormalizedSegment,
    NormalizedTranscript,
    NormalizedWord,
)
from citizens.services.audio import AudioAssemblyError, _ffprobe, _remux
from citizens.services.recording_states import transition
from citizens.services.transcription import store_transcript
from citizens.storage.durable import sync_directory
from citizens.storage.paths import assembled_dir, temp_dir

log = get_logger(__name__)

SUPPORTED_FORMATS = (1, 2)
LANGUAGES = ("en", "it", "de", "fr", "es")
MAX_SEGMENTS = 50_000
MAX_SEGMENT_CHARS = 10_000
#: a recording may get a transcript from outside in any of these: the ones
#: whose own transcription never happened or failed, and the ones that have
#: one already (replacing it, as a re-transcription does)
TRANSCRIPT_ATTACHABLE = (
    "AUDIO_INVALID", "UPLOAD_INCOMPLETE", "TRANSCRIPTION_FAILED", "AUDIO_READY",
    "TRANSCRIBED", "READY_FOR_REVIEW", "REVIEWED", "ANALYSIS_FAILED",
)
#: audio from outside only where the server has none of its own
AUDIO_ATTACHABLE = ("AUDIO_INVALID", "UPLOAD_INCOMPLETE", "TRANSCRIPTION_FAILED")
_EXTENSIONS = {"mp4": ".m4a", "ogg": ".ogg", "mpeg": ".mp3", "wav": ".wav", "x-wav": ".wav"}


class ImportError_(Exception):
    """A refusal the organizer can act on (422), never a server fault."""


# --- transcripts from outside ---------------------------------------------

def parse_transcript(data: dict, fallback_language: str = "") -> NormalizedTranscript:
    """The export's transcripts/<id>.json, or GET /recordings/{id}/transcript,
    or a bare {"segments": [...]}: provider, model and language as given,
    segments in order."""
    if not isinstance(data, dict):
        raise ImportError_("The transcript must be a JSON object")
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ImportError_("The transcript has no segments")
    if len(segments) > MAX_SEGMENTS:
        raise ImportError_(f"The transcript has more than {MAX_SEGMENTS} segments")
    rows: list[NormalizedSegment] = []
    for index, item in enumerate(segments):
        if not isinstance(item, dict):
            raise ImportError_(f"Segment {index} is not an object")
        try:
            start = float(item.get("start", 0.0) or 0.0)
            end = float(item.get("end", start) or start)
        except (TypeError, ValueError) as exc:
            raise ImportError_(f"Segment {index} has a non-numeric time") from exc
        text = item.get("text", "")
        if not isinstance(text, str):
            raise ImportError_(f"Segment {index} has no text")
        text = " ".join(text.split())[:MAX_SEGMENT_CHARS]
        if not text:
            continue
        speaker = item.get("speaker") or item.get("speaker_label") or ""
        words = []
        for word in item.get("words") or []:
            if isinstance(word, dict) and isinstance(word.get("text"), str):
                try:
                    words.append(NormalizedWord(
                        text=word["text"][:200], start=float(word.get("start", start)),
                        end=float(word.get("end", end)),
                    ))
                except (TypeError, ValueError):
                    continue
        rows.append(NormalizedSegment(
            speaker=str(speaker)[:20], start=max(0.0, start), end=max(start, end),
            text=text, words=words,
        ))
    if not rows:
        raise ImportError_("Every segment of the transcript is empty")
    raw = data.get("raw") if isinstance(data.get("raw"), dict) else {}
    return NormalizedTranscript(
        provider=str(data.get("provider") or "imported")[:20],
        model=str(data.get("model") or "")[:80],
        language=str(data.get("language") or fallback_language)[:10],
        segments=rows,
        raw=raw,
    )


def attach_transcript(session: Session, recording: Recording, data: dict) -> int:
    """A transcript made elsewhere becomes this recording's; returns the
    segment count. The recording ends TRANSCRIBED, so the table's analysis
    can run — the caller queues it."""
    if recording.state not in TRANSCRIPT_ATTACHABLE:
        raise ImportError_(f"A transcript cannot be attached while the recording is {recording.state}")
    assembly = session.get(Assembly, recording.assembly_id)
    normalized = parse_transcript(data, assembly.language if assembly else "")
    store_transcript(session, recording, normalized, source="final")
    if recording.state != "TRANSCRIBED":
        transition(recording, "TRANSCRIBED")
    recording.transcript_deleted_at = None
    recording.error_code = ""
    if recording.duration_seconds is None:
        recording.duration_seconds = max(s.end for s in normalized.segments)
    log.info(
        "transcript_attached", recording_id=recording.id, segments=len(normalized.segments),
        provider=normalized.provider,
    )
    return len(normalized.segments)


# --- audio from outside ---------------------------------------------------

def extension_for(mime_type: str) -> str:
    subtype = (mime_type or "").split(";")[0].split("/")[-1].strip().lower()
    return _EXTENSIONS.get(subtype, ".webm")


@dataclass
class PreparedAudio:
    canonical_relative: str
    sha256: str
    duration: float | None
    bytes: int


def prepare_audio(assembly_id: str, recording_id: str, source: Path, mime_type: str) -> PreparedAudio:
    """ffprobe the file and remux it (stream copy) into the recording's
    canonical place, as assemble_recording does. No database: call it with
    no session open, then attach_audio() with one."""
    try:
        duration = _ffprobe(source).get("duration")
    except AudioAssemblyError as exc:
        raise ImportError_(f"The file is not audio this server can read: {exc}") from exc
    root = get_settings().app_persistent_storage
    canonical = assembled_dir(root, assembly_id) / f"{recording_id}{extension_for(mime_type)}"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    try:
        _remux(source, canonical)
    except AudioAssemblyError as exc:
        raise ImportError_(f"The file could not be stored as audio: {exc}") from exc
    with canonical.open("rb") as audio:
        digest = hashlib.file_digest(audio, "sha256").hexdigest()
        os.fsync(audio.fileno())
    sync_directory(canonical.parent)
    return PreparedAudio(
        canonical_relative=str(canonical.relative_to(root)),
        sha256=digest,
        duration=duration or _ffprobe(canonical).get("duration"),
        bytes=canonical.stat().st_size,
    )


def attach_audio(session: Session, recording: Recording, prepared: PreparedAudio, mime_type: str) -> None:
    """The prepared file becomes this recording's audio. Ends AUDIO_READY;
    the caller queues transcription."""
    if recording.state not in AUDIO_ATTACHABLE:
        raise ImportError_(f"Audio cannot be attached while the recording is {recording.state}")
    recording.canonical_audio_path = prepared.canonical_relative
    recording.sha256 = prepared.sha256
    recording.mime_type = mime_type or "audio/webm"
    recording.duration_seconds = prepared.duration
    recording.audio_deleted_at = None
    recording.audio_added_at = utcnow()
    recording.error_code = ""
    transition(recording, "AUDIO_READY")
    log.info("audio_attached", recording_id=recording.id, bytes=prepared.bytes)


# --- a whole session: stage on disk, then write rows -------------------------

def _when(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@dataclass
class StagedRecording:
    old_id: str
    round_id: str
    table_number: int
    mime_type: str
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: float | None
    #: an extracted, checksum-verified audio file in the staging dir, or None
    audio: Path | None = None
    audio_sha256: str = ""
    audio_extension: str = ".webm"
    transcript: NormalizedTranscript | None = None


@dataclass
class StagedArchive:
    manifest: dict
    directory: Path
    recordings: list[StagedRecording] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def cleanup(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


def read_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except KeyError as exc:
        raise ImportError_("This archive has no manifest.json; it is not a session export") from exc
    except ValueError as exc:
        raise ImportError_("The archive's manifest.json is not valid JSON") from exc
    version = manifest.get("format_version")
    if version not in SUPPORTED_FORMATS:
        raise ImportError_(f"Session export format {version!r} is not supported here")
    if not isinstance(manifest.get("assembly"), dict) or not manifest.get("rounds"):
        raise ImportError_("The manifest has no assembly or no rounds")
    return manifest


def stage_archive(archive_path: Path) -> StagedArchive:
    """Read the manifest, parse every transcript and extract every audio file
    (verified against the manifest's SHA-256) into a staging directory on
    the storage disk. No database."""
    root = get_settings().app_persistent_storage
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise ImportError_("The file is not a zip archive") from exc
    staging = temp_dir(root) / "imports" / str(uuid.uuid4())
    staging.mkdir(parents=True, exist_ok=False)
    staged = StagedArchive(manifest={}, directory=staging)
    try:
        with archive:
            staged.manifest = read_manifest(archive)
            names = set(archive.namelist())
            language = staged.manifest["assembly"].get("language") or "en"
            for item in staged.manifest.get("recordings") or []:
                old_id = str(item.get("id") or "")
                number = int(item.get("table_number") or 0)
                row = StagedRecording(
                    old_id=old_id,
                    round_id=str(item.get("round_id")),
                    table_number=number,
                    mime_type=str(item.get("mime_type") or "audio/webm")[:80],
                    started_at=_when(item.get("started_at")),
                    ended_at=_when(item.get("ended_at")),
                    duration_seconds=item.get("duration_seconds"),
                )
                audio_name = item.get("audio_file")
                if audio_name and audio_name in names:
                    target = staging / f"{old_id}{Path(audio_name).suffix or '.webm'}"
                    digest = hashlib.sha256()
                    with archive.open(audio_name) as src, target.open("wb") as dst:
                        while chunk := src.read(1024 * 1024):
                            digest.update(chunk)
                            dst.write(chunk)
                    expected = (item.get("sha256") or "").lower()
                    if expected and digest.hexdigest() != expected:
                        target.unlink(missing_ok=True)
                        staged.skipped.append(
                            f"table {number}: the audio file's checksum does not match the manifest"
                        )
                    else:
                        row.audio = target
                        row.audio_sha256 = digest.hexdigest()
                        row.audio_extension = target.suffix
                elif audio_name:
                    staged.skipped.append(
                        f"table {number}: audio file {audio_name} is missing from the archive"
                    )
                transcript_name = f"transcripts/{old_id}.json"
                if transcript_name in names:
                    try:
                        data = json.loads(archive.read(transcript_name))
                        raw_name = f"transcripts/{old_id}.raw.json"
                        if raw_name in names and "raw" not in data:
                            try:
                                data["raw"] = json.loads(archive.read(raw_name))
                            except ValueError:
                                pass
                        row.transcript = parse_transcript(data, language)
                    except (ValueError, ImportError_) as exc:
                        staged.skipped.append(f"table {number}: transcript not taken ({exc})")
                staged.recordings.append(row)
    except BaseException:
        staged.cleanup()
        raise
    return staged


def import_session(
    session: Session,
    user: str,
    staged: StagedArchive,
    *,
    name: str | None = None,
    merge_tables: dict[int, int] | None = None,
) -> dict:
    """Create the archive's assembly here, closed, with everything the
    pipeline needs to analyse it again. Returns what was made and what was
    left out, in words. Audio files are renamed from the staging directory,
    which is on the same disk."""
    merges = dict(merge_tables or {})
    for source, target in merges.items():
        if source == target or target in merges:
            raise ImportError_(f"Table {source} cannot be merged into table {target}")
    skipped = list(staged.skipped)
    root = get_settings().app_persistent_storage
    manifest = staged.manifest
    source_assembly = manifest["assembly"]

    language = source_assembly.get("language") or "en"
    if language not in LANGUAGES:
        skipped.append(f"language {language!r} is not supported; set to English")
        language = "en"
    mode = source_assembly.get("recording_mode") or "orchestrated"
    if mode not in ("orchestrated", "independent", "plenary"):
        mode = "orchestrated"
    assembly = Assembly(
        name=(name or source_assembly.get("name") or "Imported session").strip()[:200],
        description=str(source_assembly.get("description") or "")[:4000],
        language=language,
        recording_mode=mode,
        expected_participants=int(source_assembly.get("expected_participants") or 0),
        default_table_count=max(1, int(source_assembly.get("default_table_count") or 1)),
        analysis_instructions=str(source_assembly.get("analysis_instructions") or "")[:4000],
        created_by=user,
        status="COMPLETE",
        closed_at=_when(source_assembly.get("closed_at")) or utcnow(),
        # no phone ever recorded for this copy; nothing to purge from one
        auto_purge_device_audio=False,
    )
    session.add(assembly)

    rounds_by_old_id: dict[str, Round] = {}
    tables_by_round: dict[str, dict[int, Table]] = {}
    for item in manifest["rounds"]:
        round_ = Round(
            position=int(item.get("position") or len(rounds_by_old_id) + 1),
            title=str(item.get("title") or "")[:200],
            question=str(item.get("question") or ""),
            duration_minutes=int(item.get("duration_minutes") or 30),
            status="ENDED",
        )
        assembly.rounds.append(round_)
        rounds_by_old_id[str(item.get("id"))] = round_
        numbers = [int(t.get("number") or 0) for t in item.get("tables") or []]
        by_number: dict[int, Table] = {}
        for table_item in item.get("tables") or []:
            number = int(table_item.get("number") or 0)
            if number <= 0 or number in by_number or number in merges:
                continue  # a merged-away table's recordings go to the other
            table = Table(
                number=number, label=str(table_item.get("label") or "")[:100],
                color_key=color_for(number),
            )
            round_.tables.append(table)
            by_number[number] = table
        for source, target in merges.items():
            if source in numbers and target not in by_number:
                skipped.append(f"table {source} could not be merged: table {target} is not in the round")
        tables_by_round[str(item.get("id"))] = by_number
    session.flush()

    participants = 0
    for item in manifest.get("participants") or []:
        if not isinstance(item, dict) or not item.get("label"):
            continue
        session.add(Participant(
            assembly_id=assembly.id,
            label=str(item["label"])[:50],
            name=str(item.get("name") or "")[:200],
            email=str(item.get("email") or "")[:200],
            notes=str(item.get("notes") or ""),
            source=str(item.get("source") or "ORGANIZER")[:16],
            registered_table_number=item.get("registered_table_number"),
        ))
        participants += 1

    recordings = transcripts = audio_files = 0
    for row in staged.recordings:
        round_ = rounds_by_old_id.get(row.round_id)
        if round_ is None:
            skipped.append(f"recording {row.old_id[:8]}: its round is not in the archive")
            continue
        table = tables_by_round[row.round_id].get(merges.get(row.table_number, row.table_number))
        if table is None:
            skipped.append(f"recording {row.old_id[:8]}: table {row.table_number} is not in the round")
            continue
        recording = Recording(
            assembly_id=assembly.id,
            round_id=round_.id,
            table_id=table.id,
            table_number=table.number,
            state="UPLOAD_INCOMPLETE",
            mime_type=row.mime_type,
            started_at=row.started_at,
            ended_at=row.ended_at,
            duration_seconds=row.duration_seconds,
            # siblings of one table are read oldest first by created_at
            created_at=row.started_at or utcnow(),
            closed_by="organizer",
        )
        session.add(recording)
        session.flush()
        recordings += 1
        if row.audio is not None:
            canonical = assembled_dir(root, assembly.id) / f"{recording.id}{row.audio_extension}"
            canonical.parent.mkdir(parents=True, exist_ok=True)
            os.replace(row.audio, canonical)
            sync_directory(canonical.parent)
            recording.canonical_audio_path = str(canonical.relative_to(root))
            recording.sha256 = row.audio_sha256
            recording.state = "AUDIO_READY"
            audio_files += 1
        if row.transcript is not None:
            store_transcript(session, recording, row.transcript, source="final")
            recording.state = "TRANSCRIBED"
            if recording.duration_seconds is None:
                recording.duration_seconds = max(s.end for s in row.transcript.segments)
            transcripts += 1

    session.flush()
    log.info(
        "session_imported", assembly_id=assembly.id, rounds=len(assembly.rounds),
        recordings=recordings, transcripts=transcripts, audio_files=audio_files,
        skipped=len(skipped),
    )
    return {
        "assembly_id": assembly.id,
        "name": assembly.name,
        "rounds": len(assembly.rounds),
        "tables": sum(len(r.tables) for r in assembly.rounds),
        "participants": participants,
        "recordings": recordings,
        "transcripts": transcripts,
        "audio_files": audio_files,
        "skipped": skipped,
    }
