# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Periodic upkeep the reactive job queue cannot express.

The runner only acts when something enqueues work. A phone whose battery dies
mid-upload enqueues nothing, so its recording stayed in WAITING_FOR_CHUNKS
forever — and because that state counts as healthy-pending, the round's
cross-table analysis waited on it too. One dead phone wedged the whole round,
with no organizer action that could resolve it.

Sweeps are best-effort: a failure is logged and retried on the next tick, and
must never take a recording's audio with it.
"""

import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

from citizens.db.models import Assembly, Recording
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.jobs.handlers import maybe_enqueue_round_analysis
from citizens.logging_setup import get_logger
from citizens.services.audit import record_audit_event
from citizens.services.jobs import has_live_job
from citizens.services.live_captions import LIVE_CAPTIONS
from citizens.services.recording_states import transition

log = get_logger(__name__)

SWEEP_INTERVAL_SECONDS = 60.0
# How long a recording may sit in WAITING_FOR_CHUNKS with no progress at all
# before we stop waiting for it. Generous: a phone that regains signal an hour
# later still re-uploads, because UPLOAD_INCOMPLETE transitions back.
STALLED_UPLOAD_MINUTES = 20
# A recording stuck in ASSEMBLING gets its own, longer, cutoff: assembly is
# real work (concatenate, ffprobe, remux) and a long round on a busy instance
# can legitimately take a while. This only fires when no ASSEMBLE_AUDIO job is
# still queued, running or backing off for it — i.e. when nothing is going to
# move it, ever.
STALLED_ASSEMBLY_MINUTES = 30


def sweep_stalled_uploads() -> int:
    """Give up on recordings that have made no progress, so the round can finish.

    Covers every state a dead phone can leave behind, not just
    WAITING_FOR_CHUNKS: a battery that dies mid-round strands the recording in
    RECORDING, which blocks the round's analysis and the table's ability to
    start over exactly the same way. (Observed on a live instance: three
    recordings stuck in RECORDING from abandoned sessions.)

    `updated_at` bumps on every received chunk, so the clock restarts whenever
    a phone makes any progress — this only fires on genuine silence. And it is
    reversible: a phone that reappears resumes uploading, which moves the
    recording back to WAITING_FOR_CHUNKS.
    """
    cutoff = utcnow() - timedelta(minutes=STALLED_UPLOAD_MINUTES)
    assembly_cutoff = utcnow() - timedelta(minutes=STALLED_ASSEMBLY_MINUTES)
    with session_scope() as session:
        stalled = list(
            session.execute(
                select(Recording).where(
                    Recording.state.in_(("WAITING_FOR_CHUNKS", "RECORDING", "FINALIZING")),
                    Recording.updated_at < cutoff,
                )
            ).scalars()
        )
        # ASSEMBLING is a trap without this: StorageFullError is retryable, so
        # it leaves the state alone, and when the attempts run out the job is
        # FAILED while the recording stays ASSEMBLING — where nothing can
        # re-record it, abandon it or retry it, and where it blocks the round's
        # cross-table analysis for good.
        wedged = [
            recording
            for recording in session.execute(
                select(Recording).where(
                    Recording.state == "ASSEMBLING",
                    Recording.updated_at < assembly_cutoff,
                )
            ).scalars()
            if not has_live_job(session, "ASSEMBLE_AUDIO", "recording_id", recording.id)
        ]
        for recording in wedged:
            log.warning(
                "assembly_abandoned",
                recording_id=recording.id,
                table_number=recording.table_number,
                error_code=recording.error_code,
            )
        stalled.extend(wedged)
        for recording in stalled:
            if not recording.error_code:
                recording.error_code = "UPLOAD_TIMED_OUT"
            transition(recording, "UPLOAD_INCOMPLETE")
            log.warning(
                "upload_abandoned",
                recording_id=recording.id,
                table_number=recording.table_number,
                received_chunks=recording.received_chunks,
                total_chunks=recording.total_chunks,
            )
        if stalled:
            session.flush()
            # the round was waiting on these; it can proceed now
            for recording in stalled:
                maybe_enqueue_round_analysis(session, recording)
        stalled_ids = [recording.id for recording in stalled]

    # Outside the transaction: these phones are gone, so nothing else will end
    # their caption sessions — /complete never arrives. An unended session
    # never persists what it heard and holds its provider connection open.
    for recording_id in stalled_ids:
        LIVE_CAPTIONS.finish(recording_id)
    return len(stalled_ids)


def _retention_days(assembly, default_days: int) -> int:
    """0 means keep indefinitely; a per-assembly value overrides the default."""
    if assembly.audio_retention_days is None:
        return default_days
    return assembly.audio_retention_days


def sweep_expired_audio() -> int:
    """Delete audio for assemblies whose retention window has passed.

    Audio only: transcripts, findings and reports are the record of the
    assembly and are never touched here. The clock starts at `closed_at`, so an
    assembly still in progress is never affected however long it runs.
    """
    from citizens.services import files as files_svc
    from citizens.services import provider_config

    # Read the config with NO transaction open. Doing it inside session_scope()
    # held SQLite's single write slot across two HTTPS round-trips to Nextcloud,
    # every 60 seconds, and chunk uploads that landed in that window exceeded
    # busy_timeout and failed with "database is locked" (see runner.py's
    # contract — this is the same rule, and this sweep broke it).
    with session_scope() as session:
        pending = session.execute(
            select(func.count())
            .select_from(Assembly)
            .where(Assembly.closed_at.is_not(None), Assembly.audio_purged_at.is_(None))
        ).scalar_one()
    if not pending:
        return 0
    try:
        default_days = int(provider_config.get_setting(
            provider_config.default_store(), "audio_retention_days"
        ) or 0)
    except Exception:
        log.warning("retention_default_unavailable", exc_info=True)
        return 0

    now = utcnow()
    purged = 0
    with session_scope() as session:
        candidates = list(
            session.execute(
                select(Assembly).where(
                    Assembly.closed_at.is_not(None), Assembly.audio_purged_at.is_(None)
                )
            ).scalars()
        )
        for assembly in candidates:
            days = _retention_days(assembly, default_days)
            if days <= 0 or assembly.closed_at + timedelta(days=days) > now:
                continue
            # audio only — transcripts and findings are the record of the
            # assembly, so quoted evidence keeps rendering after the purge
            count, freed = files_svc.delete_assembly_audio(session, assembly)
            assembly.audio_purged_at = now
            purged += 1
            record_audit_event(
                session, "audio_retention_purge", "assembly", assembly.id, actor="system",
                data={"retention_days": days, "recordings": count, "freed_bytes": freed},
            )
            log.info(
                "audio_retention_purge",
                assembly_id=assembly.id, retention_days=days,
                recordings=count, freed_bytes=freed,
            )
    return purged


#: an export archive is a throwaway build artifact; nothing should keep one
EXPORT_TTL_MINUTES = 60


def sweep_stale_exports() -> int:
    """Remove generated archives nobody collected.

    _zip_response unlinks the archive in a Starlette BackgroundTask once it has
    been streamed. That task never runs if the client disconnects mid-download,
    which on a venue connection downloading a multi-gigabyte bundle is the
    normal outcome rather than the exceptional one. Each abandoned archive is a
    complete second copy of the assembly's audio.

    Touches no database at all, so it holds no lock.
    """
    from citizens.config import get_settings

    root = Path(get_settings().app_persistent_storage) / "exports"
    if not root.is_dir():
        return 0
    cutoff = time.time() - EXPORT_TTL_MINUTES * 60
    removed = 0
    for archive in root.glob("*/*.zip"):
        try:
            if archive.stat().st_mtime >= cutoff:
                continue
            freed = archive.stat().st_size
            archive.unlink(missing_ok=True)
        except OSError:
            log.warning("stale_export_cleanup_failed", path=str(archive), exc_info=True)
            continue
        removed += 1
        log.info("stale_export_removed", path=archive.name, freed_bytes=freed)
    return removed


def run_sweeps() -> None:
    for name, sweep in (
        ("stalled_uploads", sweep_stalled_uploads),
        ("expired_audio", sweep_expired_audio),
        ("stale_exports", sweep_stale_exports),
    ):
        try:
            sweep()
        except Exception:
            log.error("sweep_failed", sweep=name, exc_info=True)
