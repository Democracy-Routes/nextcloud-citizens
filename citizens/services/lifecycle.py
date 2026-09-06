# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assembly lifecycle: progress, closing, and the frozen final report.

An assembly's report is INTERIM until the organizer closes the session (or,
when every table finished, until they accept the prompt to close). Closing
snapshots the report so that reopening the session — to let a late table
record — can never change what participants already read; a later close (or an
explicit refresh) republishes an updated snapshot.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import Assembly, Recording
from citizens.db.models.base import utcnow
from citizens.logging_setup import get_logger
from citizens.services.audit import record_audit_event
from citizens.services.jobs import enqueue_job, has_live_job
from citizens.services.recording import COMPLETED_STATES, assembly_progress
from citizens.services.report import build_report

log = get_logger(__name__)

__all__ = [
    "assembly_progress",
    "close_assembly",
    "frozen_report",
    "reopen_assembly",
    "snapshot_final_report",
]


def snapshot_final_report(session: Session, assembly: Assembly) -> dict:
    """Freeze the current report as the version participants will read."""
    report = build_report(session, assembly, include_drafts=False)
    assembly.final_report_json = json.dumps(report)
    assembly.final_report_at = utcnow()
    return report


def frozen_report(assembly: Assembly) -> dict | None:
    if not assembly.final_report_json:
        return None
    try:
        return json.loads(assembly.final_report_json)
    except ValueError:
        log.warning("final_report_snapshot_unreadable", assembly_id=assembly.id)
        return None


def close_assembly(session: Session, assembly: Assembly) -> dict:
    """Finish the session: stop recordings, analyze what exists, freeze the
    report. Reversible with reopen_assembly()."""
    for round_ in assembly.rounds:
        if round_.status == "ACTIVE":
            round_.status = "ENDED"
            # end_round() sets this; force-ending here skipped it
            round_.ended_at = round_.ended_at or utcnow()
        # a round whose tables recorded but which never got aggregated (e.g.
        # tables that never showed up kept it waiting) gets a final pass.
        # Deduped: the last table's analysis may have queued the same job in
        # the same minute, and running both meant two model calls — and, if
        # the first run's clusters were approved in between, a report showing
        # both generations side by side.
        if (
            not round_.analysis_summary
            and _round_has_content(session, round_.id)
            and not has_live_job(session, "ANALYZE_ROUND", "round_id", round_.id)
        ):
            enqueue_job(session, "ANALYZE_ROUND", {"round_id": round_.id})
    assembly.closed_at = utcnow()
    assembly.status = "COMPLETE"
    # Every phone still holds its table's audio — that is what makes recording
    # survive a bad network — and when those are the participants' own devices,
    # leaving it there is the surprising outcome. Each phone deletes only what
    # the server has already confirmed, and keeps anything else, so this cannot
    # destroy a last copy; tables still assembling simply clear later, when
    # their recording reaches AUDIO_READY.
    if assembly.auto_purge_device_audio and assembly.device_audio_purge_requested_at is None:
        assembly.device_audio_purge_requested_at = utcnow()
        record_audit_event(
            session, "device_audio_purge_requested", "assembly", assembly.id,
            data={"automatic": True},
        )
    report = snapshot_final_report(session, assembly)
    log.info(
        "assembly_closed",
        assembly_id=assembly.id,
        progress=assembly_progress(session, assembly),
    )
    return report


def reopen_assembly(session: Session, assembly: Assembly) -> None:
    """Accept recordings again. The frozen snapshot stays in place, so phones
    keep showing the report exactly as it was at closing."""
    assembly.closed_at = None
    assembly.status = "ACTIVE"
    # Withdraw any standing purge request. The phone-facing flag is a bare
    # "has this been asked for", never re-checked against closed_at, so leaving
    # it set means every phone that joins the reopened assembly is still being
    # told to delete — and would clear each NEW recording the moment it reached
    # AUDIO_READY, mid-round. Harmless while purging was a button somebody had
    # to press; not harmless now that closing asks by itself. Only the
    # automatic request is withdrawn — a purge an organizer explicitly asked
    # for on a manual assembly stands.
    if assembly.auto_purge_device_audio:
        assembly.device_audio_purge_requested_at = None
    # And let retention apply to audio recorded after the reopen: the sweep
    # only considers assemblies with audio_purged_at NULL, so leaving it set
    # meant a table that recorded post-reopen was retained forever while the
    # policy reported the assembly purged.
    assembly.audio_purged_at = None
    log.info("assembly_reopened", assembly_id=assembly.id)


def _round_has_content(session: Session, round_id: str) -> bool:
    return (
        session.execute(
            select(Recording.id).where(
                Recording.round_id == round_id,
                Recording.state.in_(COMPLETED_STATES),
            )
        ).first()
        is not None
    )
