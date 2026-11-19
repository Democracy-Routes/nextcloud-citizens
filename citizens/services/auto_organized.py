# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record now sessions finish by themselves (0.9).

A container made by Record now (`assemblies.auto_organized`) has no organizer
at the keyboard. When nobody records any more the server closes it; once the
round analysis has landed it approves every finding, freezes and publishes the
report, and — with Polis configured — starts the statement seeds, whose job
approves them and sends them on. The report says no person reviewed it
(services/report._methodology_note).

Nothing here reads configuration: the callers pass `analysis_on` and `polis_on`
from the config snapshot, read outside any transaction.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from citizens.db.models import Assembly, Finding, RecorderSession, Recording
from citizens.db.models.base import utcnow
from citizens.logging_setup import get_logger
from citizens.services import findings_review, lifecycle
from citizens.services.audit import record_audit_event
from citizens.services.jobs import enqueue_job, has_live_job
from citizens.services.processing import TRANSIENT_STATES, still_processing
from citizens.services.recording import COMPLETED_STATES

log = get_logger(__name__)

#: the only recorder session ever to join: it closes on the next sweep after
#: its recording finished (seconds)
SINGLE_PHONE_IDLE_SECONDS = 60
SYSTEM_ACTOR = "system"
APPROVED = ("APPROVED", "EDITED_AND_APPROVED")
#: completed recordings that no analysis can come from
_NO_ANALYSIS_STATES = ("TRANSCRIPTION_FAILED", "ANALYSIS_FAILED")


def idle_threshold_seconds(recorder_sessions: int, minutes: int) -> int | None:
    """How long after its last recording a Record now session closes: never
    (0 minutes), a minute when one phone was all there ever was, otherwise
    the setting."""
    if minutes <= 0:
        return None
    if recorder_sessions == 1:
        return SINGLE_PHONE_IDLE_SECONDS
    return minutes * 60


def _round_settled(session: Session, round_, *, analysis_on: bool) -> bool:
    """Nothing more will change this round's findings."""
    if not analysis_on:
        return True
    if round_.analysis_summary and (
        (round_.analysis_input_revision or 0) <= (round_.analysis_applied_revision or 0)
    ):
        return True
    states = [
        state for (state,) in session.execute(
            select(Recording.state).where(
                Recording.round_id == round_.id, Recording.state.in_(COMPLETED_STATES)
            )
        )
    ]
    # no content, or every recording failed: no ANALYZE_ROUND will ever land
    return all(state in _NO_ANALYSIS_STATES for state in states)


def ready_to_finalize(
    session: Session, assembly: Assembly, *, analysis_on: bool,
    running_round_id: str | None = None,
) -> bool:
    if (
        not assembly.auto_organized
        or assembly.closed_at is None
        or assembly.auto_finalized_at is not None
    ):
        return False
    if still_processing(session, assembly, running_round_id=running_round_id) is not None:
        return False
    return all(_round_settled(session, r, analysis_on=analysis_on) for r in assembly.rounds)


def finalize(session: Session, assembly: Assembly, *, polis_on: bool) -> dict:
    """Approve, freeze, publish, and start the Polis cycle. Once: the stamp."""
    approved = 0
    for round_ in assembly.rounds:
        # table AND round scope: the round's cross-table findings are drafts too
        approved += findings_review.approve_drafts(
            session, round_, actor=findings_review.AUTO_REVIEWER, automatic=True
        )
    lifecycle.snapshot_final_report(session, assembly)
    now = utcnow()
    assembly.report_published_at = assembly.report_published_at or now
    assembly.auto_finalized_at = now
    record_audit_event(
        session, "report_published", "assembly", assembly.id,
        actor=SYSTEM_ACTOR, data={"automatic": True},
    )
    record_audit_event(
        session, "session_auto_finalized", "assembly", assembly.id,
        actor=SYSTEM_ACTOR, data={"findings_approved": approved},
    )
    seeds = False
    if polis_on and not has_live_job(session, "SEED_STATEMENTS", "assembly_id", assembly.id):
        any_approved = session.execute(
            select(func.count()).select_from(Finding).where(
                Finding.assembly_id == assembly.id, Finding.status.in_(APPROVED)
            )
        ).scalar_one()
        if any_approved:
            enqueue_job(
                session, "SEED_STATEMENTS",
                {"assembly_id": assembly.id, "target": None, "automatic": True},
                max_attempts=3,
            )
            seeds = True
    session.flush()
    log.info("session_auto_finalized", assembly_id=assembly.id, findings_approved=approved, seeds=seeds)
    return {"findings_approved": approved, "seeds_enqueued": seeds}


def finalize_if_ready(
    session: Session, assembly: Assembly, *, analysis_on: bool, polis_on: bool,
    running_round_id: str | None = None,
) -> bool:
    """`running_round_id`: set by the ANALYZE_ROUND handler, whose own job is
    still RUNNING when it calls this."""
    if not ready_to_finalize(
        session, assembly, analysis_on=analysis_on, running_round_id=running_round_id
    ):
        return False
    finalize(session, assembly, polis_on=polis_on)
    return True


def sweep_idle_close(now: datetime, *, minutes: int, analysis_on: bool, polis_on: bool) -> int:
    """Close Record now sessions nobody records in any more, then finish the
    closed ones whose analysis has landed. The caller read the settings."""
    from citizens.db.session import session_scope

    closed = 0
    with session_scope() as session:
        if minutes > 0:
            candidates = list(
                session.execute(
                    select(Assembly).where(
                        Assembly.auto_organized.is_(True), Assembly.closed_at.is_(None)
                    )
                ).scalars()
            )
            for assembly in candidates:
                recordings = list(
                    session.execute(
                        select(Recording).where(Recording.assembly_id == assembly.id)
                    ).scalars()
                )
                # CREATED never started and UPLOAD_INCOMPLETE is already a
                # silent phone: neither holds a session open, the clock does.
                # A session where no phone ever started stays open: nothing
                # was said, so there is nothing to close and publish.
                if (
                    not recordings
                    or all(r.state == "CREATED" for r in recordings)
                    or any(
                        r.state in TRANSIENT_STATES and r.state != "CREATED" for r in recordings
                    )
                ):
                    continue
                last = max(r.ended_at or r.updated_at for r in recordings)
                phones = session.execute(
                    select(func.count()).select_from(RecorderSession).where(
                        RecorderSession.assembly_id == assembly.id
                    )
                ).scalar_one()
                threshold = idle_threshold_seconds(phones, minutes)
                if threshold is None or (now - last).total_seconds() <= threshold:
                    continue
                lifecycle.close_assembly(
                    session, assembly, analysis_on=analysis_on, polis_on=polis_on
                )
                record_audit_event(
                    session, "assembly_closed", "assembly", assembly.id, actor=SYSTEM_ACTOR,
                    data={
                        "automatic": True, "reason": "idle",
                        "progress": lifecycle.assembly_progress(session, assembly),
                    },
                )
                closed += 1
                log.info("auto_organized_idle_closed", assembly_id=assembly.id)
        waiting = list(
            session.execute(
                select(Assembly).where(
                    Assembly.auto_organized.is_(True),
                    Assembly.closed_at.is_not(None),
                    Assembly.auto_finalized_at.is_(None),
                )
            ).scalars()
        )
        for assembly in waiting:
            finalize_if_ready(session, assembly, analysis_on=analysis_on, polis_on=polis_on)
    return closed
