# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Participant registration and individual consent at the table (0.7).

A person at a table gives their name (email optional), reads the notice the
server rendered, ticks what they consent to, confirms. The record is stored
as given — a refusal is a record too, like the paper form's "I do not
consent" — with the hash of the notice as shown. One row per act; nothing
here is a table-level tick.

The assembly's rule decides what the record means for recording: 'required'
means a table records only once one registered person there has consented
to recording; 'optional' blocks nothing. The rule is enforced in
start_recording, never only in the UI.
"""

from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from citizens.db.models import (
    Assembly,
    ConsentNotice,
    Participant,
    ParticipantConsent,
    ParticipantSession,
    RecorderInvite,
    RecorderSession,
    Recording,
    Round,
    Table,
    TableAssignment,
)
from citizens.db.models.base import utcnow
from citizens.domain.tables import color_for
from citizens.security.recorder_tokens import generate_token, hash_token
from citizens.services import invites as invite_svc
from citizens.services.audit import record_audit_event
from citizens.services.consent_notice import Notice, render_notice
from citizens.services.provider_config import config_snapshot, organization_data
from citizens.services.recording import RERECORDABLE_STATES

CONSENT_REQUIRED_CODE = "PARTICIPANT_CONSENT_REQUIRED"


@dataclass(frozen=True)
class ConsentAct:
    """What a person ticked, as the phone sent it."""

    name: str
    email: str
    notice_hash: str
    notice_read: bool
    recording_consent: bool
    transcription_consent: bool
    analysis_consent: bool
    publication_consent: bool


def notice_for(assembly: Assembly) -> Notice:
    """The current notice for this assembly, from the config snapshot (an
    in-memory read — safe on a read session, never an OCS call)."""
    snapshot = config_snapshot()
    handling = dict(snapshot.data_handling)
    if assembly.audio_retention_days is not None:
        handling["audio_retention_days"] = assembly.audio_retention_days
    return render_notice(
        assembly.language,
        handling,
        organization=organization_data(),
        auto_purge=bool(assembly.auto_purge_device_audio),
    )


def next_label(session: Session, assembly_id: str) -> str:
    """The next free P001-style label — the shape the organizer's CSV uses."""
    existing = {
        label
        for (label,) in session.execute(
            select(Participant.label).where(Participant.assembly_id == assembly_id)
        )
    }
    n = len(existing) + 1
    while f"P{n:03d}" in existing:
        n += 1
    return f"P{n:03d}"


def _round_being_set_up(session: Session, assembly_id: str, table_number: int) -> Round | None:
    """The round this table will record next: the first one it has not
    recorded (an ACTIVE one first), so the person is seated where they are."""
    rounds = list(
        session.execute(
            select(Round).where(Round.assembly_id == assembly_id).order_by(Round.position)
        ).scalars()
    )
    recorded = {
        round_id
        for (round_id,) in session.execute(
            select(Recording.round_id).where(
                Recording.assembly_id == assembly_id,
                Recording.table_number == table_number,
                Recording.state.notin_(RERECORDABLE_STATES),
                Recording.superseded_at.is_(None),
            )
        )
    }
    active = next((r for r in rounds if r.status == "ACTIVE" and r.id not in recorded), None)
    if active is not None:
        return active
    return next((r for r in rounds if r.status != "ENDED" and r.id not in recorded), None)


def register(
    session: Session,
    assembly: Assembly,
    act: ConsentAct,
    *,
    method: str,
    table_number: int,
    recorder_session: RecorderSession | None = None,
    notice: Notice | None = None,
) -> tuple[Participant, ParticipantConsent]:
    """Store one person and one consent act at `table_number`.

    `notice` is the server's current notice (read by the caller outside the
    transaction); the act must carry its hash, or the person read a stale
    text and is asked to read the current one (409).
    """
    if notice is None:
        notice = notice_for(assembly)
    name = act.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="A name is required")
    if act.notice_hash != notice.hash:
        raise HTTPException(
            status_code=409,
            detail={"code": "NOTICE_CHANGED", "message": "The notice has changed — please read it again"},
        )
    if session.get(ConsentNotice, notice.hash) is None:
        session.add(
            ConsentNotice(
                hash=notice.hash, version=notice.version, language=notice.language, text=notice.text
            )
        )
        session.flush()
    round_ = _round_being_set_up(session, assembly.id, table_number)
    participant = Participant(
        assembly_id=assembly.id,
        label=next_label(session, assembly.id),
        name=name[:200],
        email=act.email.strip()[:200],
        source=method if method in ("TABLE_DEVICE", "SELF_PHONE") else "ORGANIZER",
        registered_table_number=table_number,
        registered_round_id=round_.id if round_ else None,
        registered_session_id=recorder_session.id if recorder_session else None,
    )
    session.add(participant)
    session.flush()
    consent = ParticipantConsent(
        assembly_id=assembly.id,
        participant_id=participant.id,
        round_id=round_.id if round_ else None,
        table_number=table_number,
        recorder_session_id=recorder_session.id if recorder_session else None,
        method=method,
        notice_hash=notice.hash,
        notice_version=notice.version,
        notice_language=notice.language,
        notice_read=act.notice_read,
        recording_consent=act.recording_consent,
        transcription_consent=act.transcription_consent,
        analysis_consent=act.analysis_consent,
        publication_consent=act.publication_consent,
        confirmed_at=utcnow(),
    )
    session.add(consent)
    # seat the person at the table for the round being set up, so the Tables
    # tab shows them where they are
    if round_ is not None:
        table = session.execute(
            select(Table).where(Table.round_id == round_.id, Table.number == table_number)
        ).scalar_one_or_none()
        if table is not None:
            session.add(
                TableAssignment(round_id=round_.id, table_id=table.id, participant_id=participant.id)
            )
    session.flush()
    record_audit_event(
        session, "participant_registered", "participant", participant.id,
        data={
            "table": table_number,
            "round_id": round_.id if round_ else None,
            "method": method,
            "notice_version": notice.version,
            "notice_hash": notice.hash,
            "recording": act.recording_consent,
            "transcription": act.transcription_consent,
            "analysis": act.analysis_consent,
            "publication": act.publication_consent,
        },
    )
    return participant, consent


def latest_consents(session: Session, assembly_id: str) -> dict[str, ParticipantConsent]:
    """Each participant's newest consent act, by participant id."""
    rows = session.execute(
        select(ParticipantConsent)
        .where(ParticipantConsent.assembly_id == assembly_id)
        .order_by(ParticipantConsent.confirmed_at.asc(), ParticipantConsent.created_at.asc())
    ).scalars()
    latest: dict[str, ParticipantConsent] = {}
    for consent in rows:
        latest[consent.participant_id] = consent
    return latest


def consent_dict(consent: ParticipantConsent | None) -> dict | None:
    if consent is None:
        return None
    return {
        "method": consent.method,
        "notice_version": consent.notice_version,
        "notice_hash": consent.notice_hash,
        "notice_language": consent.notice_language,
        "notice_read": consent.notice_read,
        "recording": consent.recording_consent,
        "transcription": consent.transcription_consent,
        "analysis": consent.analysis_consent,
        "publication": consent.publication_consent,
        "confirmed_at": consent.confirmed_at,
        "withdrawn_at": consent.withdrawn_at,
    }


def table_roster(session: Session, assembly_id: str, table_number: int) -> list[dict]:
    """Who registered at this table, for the phone: names only, never email."""
    latest = latest_consents(session, assembly_id)
    people = session.execute(
        select(Participant)
        .where(
            Participant.assembly_id == assembly_id,
            Participant.registered_table_number == table_number,
        )
        .order_by(Participant.created_at.asc())
    ).scalars()
    return [
        {
            "label": p.label,
            "name": p.name,
            "recording_consent": bool(
                latest.get(p.id) and latest[p.id].recording_consent and latest[p.id].withdrawn_at is None
            ),
        }
        for p in people
    ]


def consenting_count(session: Session, assembly_id: str, table_number: int) -> int:
    """How many people registered at this table consent to recording."""
    roster = table_roster(session, assembly_id, table_number)
    return sum(1 for person in roster if person["recording_consent"])


def table_consent_state(session: Session, assembly: Assembly, table_number: int) -> dict:
    roster = table_roster(session, assembly.id, table_number)
    consenting = sum(1 for person in roster if person["recording_consent"])
    return {
        "mode": assembly.participant_consent,
        "registered": len(roster),
        "consenting": consenting,
        "can_record": assembly.participant_consent != "required" or consenting > 0,
    }


def consent_by_table(session: Session, assembly: Assembly) -> dict[int, dict]:
    """Every table's registered / consenting counts in two queries — for the
    monitor, which asks for all tables at once every few seconds."""
    latest = latest_consents(session, assembly.id)
    counts: dict[int, dict] = {}
    for participant in session.execute(
        select(Participant).where(
            Participant.assembly_id == assembly.id,
            Participant.registered_table_number.is_not(None),
        )
    ).scalars():
        entry = counts.setdefault(
            participant.registered_table_number, {"registered": 0, "consenting": 0}
        )
        entry["registered"] += 1
        consent = latest.get(participant.id)
        if consent is not None and consent.recording_consent and consent.withdrawn_at is None:
            entry["consenting"] += 1
    return {
        number: {
            "mode": assembly.participant_consent,
            **entry,
            "can_record": assembly.participant_consent != "required" or entry["consenting"] > 0,
        }
        for number, entry in counts.items()
    }


def guard_recording(session: Session, assembly: Assembly, table_number: int) -> None:
    """The rule behind 'required', enforced where recording starts."""
    if assembly.participant_consent != "required":
        return
    if consenting_count(session, assembly.id, table_number) == 0:
        raise HTTPException(
            status_code=409,
            detail={
                "code": CONSENT_REQUIRED_CODE,
                "message": "Register at least one participant who consents to recording first",
            },
        )


#: a participant's page outlives the event: the report may come weeks later
PARTICIPANT_SESSION_LIFETIME = timedelta(days=180)


def registration_code(session: Session, token: str) -> tuple[RecorderInvite, Assembly]:
    """The REGISTER_PARTICIPANT code behind a token, or 401/409."""
    invite = invite_svc.find_by_token(session, token)
    if invite is None or invite.revoked_at is not None or invite_svc.is_expired(invite):
        raise HTTPException(status_code=401, detail="Invalid or expired registration code")
    if invite.purpose != "REGISTER_PARTICIPANT" or invite.table_number is None:
        raise HTTPException(status_code=409, detail="This code does not register a participant")
    assembly = session.get(Assembly, invite.assembly_id)
    if assembly is None:
        raise HTTPException(status_code=404, detail="Assembly not found")
    if assembly.closed_at is not None:
        raise HTTPException(status_code=409, detail="This assembly has been closed by the organizer")
    return invite, assembly


def register_by_code(
    session: Session, token: str, act: ConsentAct, notice: Notice | None = None
) -> tuple[Participant, ParticipantConsent, ParticipantSession, str, RecorderInvite]:
    """A person registers on their own phone through the table's code: the
    same record as on the shared phone, method SELF_PHONE, the table known
    from the code — and a bearer for their page."""
    invite, assembly = registration_code(session, token)
    participant, consent = register(
        session, assembly, act, method="SELF_PHONE", table_number=invite.table_number, notice=notice
    )
    invite.last_used_at = utcnow()
    bearer = generate_token()
    participant_session = ParticipantSession(
        participant_id=participant.id,
        assembly_id=assembly.id,
        token_hash=hash_token(bearer),
        expires_at=utcnow() + PARTICIPANT_SESSION_LIFETIME,
    )
    session.add(participant_session)
    session.flush()
    return participant, consent, participant_session, bearer, invite


def participant_by_bearer(session: Session, bearer: str) -> ParticipantSession:
    participant_session = session.execute(
        select(ParticipantSession).where(ParticipantSession.token_hash == hash_token(bearer))
    ).scalar_one_or_none()
    if participant_session is None or participant_session.expires_at < utcnow():
        raise HTTPException(status_code=401, detail="Participant session invalid or expired")
    return participant_session


def participant_status(
    session: Session, participant_session: ParticipantSession, report_available: bool
) -> dict:
    """What a person's own page shows: where they are registered, their
    consent, whether the report is out, and whom to contact to withdraw."""
    participant = session.get(Participant, participant_session.participant_id)
    assembly = session.get(Assembly, participant_session.assembly_id)
    if participant is None or assembly is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    latest = latest_consents(session, assembly.id).get(participant.id)
    snapshot = config_snapshot()
    return {
        "assembly": {"id": assembly.id, "name": assembly.name, "language": assembly.language,
                     "kind": assembly.kind},
        "participant": {"label": participant.label, "name": participant.name},
        "table_number": participant.registered_table_number,
        "color_key": (
            color_for(participant.registered_table_number)
            if participant.registered_table_number is not None
            else None
        ),
        "consent": consent_dict(latest),
        "report_available": report_available,
        "contact": snapshot.consent_contact or organization_data().get("org_dpo", ""),
        "controller": snapshot.consent_controller or snapshot.organization_name,
    }


def participants_with_consent(session: Session, assembly: Assembly) -> list[dict]:
    """The organizer's list: each person with their newest consent act."""
    latest = latest_consents(session, assembly.id)
    return [
        {
            "id": p.id,
            "label": p.label,
            "name": p.name,
            "email": p.email,
            "notes": p.notes,
            "source": p.source,
            "registered_table_number": p.registered_table_number,
            "consent": consent_dict(latest.get(p.id)),
        }
        for p in sorted(assembly.participants, key=lambda p: (p.created_at, p.label))
    ]


def consent_counts(session: Session, assembly_id: str) -> dict:
    """For the report's methodology note: how many registered at a table, and
    how many of those consented to recording."""
    latest = latest_consents(session, assembly_id)
    registered = session.execute(
        select(func.count()).select_from(Participant).where(
            Participant.assembly_id == assembly_id, Participant.source != "ORGANIZER"
        )
    ).scalar_one()
    consenting = sum(
        1 for consent in latest.values() if consent.recording_consent and consent.withdrawn_at is None
    )
    return {"registered_at_table": int(registered), "consenting": consenting}
