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
#: someone seated at the table refused: recording there waits until they are
#: marked as moved to a table that is not recorded, or change their mind
REFUSED_CODE = "PARTICIPANT_REFUSED"


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
    table_number: int | None,
    recorder_session: RecorderSession | None = None,
    notice: Notice | None = None,
) -> tuple[Participant, ParticipantConsent]:
    """Store one person and one consent act at `table_number` (None: a
    pre-registration, seated later by name).

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
    round_ = _round_being_set_up(session, assembly.id, table_number) if table_number else None
    participant = Participant(
        assembly_id=assembly.id,
        label=next_label(session, assembly.id),
        name=name[:200],
        email=act.email.strip()[:200],
        source=method if method in ("TABLE_DEVICE", "SELF_PHONE", "PRE_REGISTRATION") else "ORGANIZER",
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
    if round_ is not None and table_number is not None:
        _seat_in_round(session, round_, table_number, participant)
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


def _seat_in_round(session: Session, round_: Round, table_number: int, participant: Participant) -> None:
    table = session.execute(
        select(Table).where(Table.round_id == round_.id, Table.number == table_number)
    ).scalar_one_or_none()
    if table is None:
        return
    existing = session.execute(
        select(TableAssignment).where(
            TableAssignment.round_id == round_.id, TableAssignment.participant_id == participant.id
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.table_id = table.id
    else:
        session.add(TableAssignment(round_id=round_.id, table_id=table.id, participant_id=participant.id))


def search_unseated(session: Session, assembly_id: str, query: str, limit: int = 10) -> list[dict]:
    """People registered ahead (no table yet) whose name contains `query` —
    the door's "find your name". Names only, never email."""
    needle = f"%{query.strip().lower()}%"
    rows = session.execute(
        select(Participant)
        .where(
            Participant.assembly_id == assembly_id,
            Participant.registered_table_number.is_(None),
            Participant.source == "PRE_REGISTRATION",
            func.lower(Participant.name).like(needle),
        )
        .order_by(Participant.name)
        .limit(limit)
    ).scalars()
    latest = latest_consents(session, assembly_id)
    return [
        {
            "id": p.id,
            "label": p.label,
            "name": p.name,
            "recording_consent": bool(latest.get(p.id) and latest[p.id].recording_consent),
        }
        for p in rows
    ]


def seat(
    session: Session, assembly: Assembly, participant_id: str, recorder_session: RecorderSession
) -> Participant:
    """A pre-registered person sits down at this phone's table: the table is
    recorded on the participant, and they are seated for the round being
    set up. Their consent act travels with them."""
    participant = session.get(Participant, participant_id)
    if participant is None or participant.assembly_id != assembly.id:
        raise HTTPException(status_code=404, detail="Participant not found")
    if participant.registered_table_number is not None:
        raise HTTPException(status_code=409, detail="This person is already seated at a table")
    table_number = recorder_session.table_number
    participant.registered_table_number = table_number
    participant.registered_session_id = recorder_session.id
    round_ = _round_being_set_up(session, assembly.id, table_number)
    if round_ is not None:
        participant.registered_round_id = round_.id
        _seat_in_round(session, round_, table_number, participant)
    session.flush()
    record_audit_event(
        session, "participant_seated", "participant", participant.id,
        data={"table": table_number, "round_id": round_.id if round_ else None},
    )
    return participant


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


def _seats(session: Session, assembly_id: str, round_id: str | None) -> dict[str, int]:
    """participant id → table number for one session: the seating plan's word
    (table_assignments, written by registration at the table and by New
    seating between sessions) first, and the registration table for anyone
    the plan has not placed in this session."""
    seats: dict[str, int] = {}
    if round_id is not None:
        for participant_id, number in session.execute(
            select(TableAssignment.participant_id, Table.number)
            .join(Table, Table.id == TableAssignment.table_id)
            .where(TableAssignment.round_id == round_id)
        ):
            seats[participant_id] = number
    for participant_id, number in session.execute(
        select(Participant.id, Participant.registered_table_number).where(
            Participant.assembly_id == assembly_id,
            Participant.registered_table_number.is_not(None),
        )
    ):
        seats.setdefault(participant_id, number)
    return seats


def _current_round_id(session: Session, assembly_id: str, table_number: int) -> str | None:
    round_ = _round_being_set_up(session, assembly_id, table_number)
    return round_.id if round_ is not None else None


def _stands(consent: ParticipantConsent | None) -> bool:
    """Does this (newest) act consent to recording?"""
    return bool(consent and consent.recording_consent and consent.withdrawn_at is None)


def _refuses(consent: ParticipantConsent | None) -> bool:
    """Is this (newest) act a refusal or a withdrawal? A person with no act
    at all (an organizer's list entry) neither consents nor refuses."""
    return bool(consent) and (not consent.recording_consent or consent.withdrawn_at is not None)


def table_roster(
    session: Session, assembly_id: str, table_number: int, round_id: str | None = None
) -> list[dict]:
    """Who sits at this table in this session (the one being set up when
    `round_id` is None), for the phone: names only, never email. The newest
    consent act counts — a change of mind, a withdrawal — and the roster says
    who refused, because that person blocks the table until marked as moved."""
    if round_id is None:
        round_id = _current_round_id(session, assembly_id, table_number)
    seats = _seats(session, assembly_id, round_id)
    ids = [pid for pid, number in seats.items() if number == table_number]
    if not ids:
        return []
    latest = latest_consents(session, assembly_id)
    people = session.execute(
        select(Participant)
        .where(Participant.id.in_(ids))
        .order_by(Participant.created_at.asc(), Participant.label.asc())
    ).scalars()
    return [
        {
            "id": p.id,
            "label": p.label,
            "name": p.name,
            "recording_consent": _stands(latest.get(p.id)),
            "publication_consent": bool(
                latest.get(p.id) and latest[p.id].publication_consent
                and latest[p.id].withdrawn_at is None
            ),
            "refused": _refuses(latest.get(p.id)),
        }
        for p in people
    ]


def _state(mode: str, registered: int, consenting: int, refusing: int) -> dict:
    return {
        "mode": mode,
        "registered": registered,
        "consenting": consenting,
        "refusing": refusing,
        # required: at least one consent AND nobody seated who refused — a
        # refusal is not outvoted, the person is moved to a table that is not
        # recorded (or changes their mind)
        "can_record": mode != "required" or (consenting > 0 and refusing == 0),
    }


def consenting_count(session: Session, assembly_id: str, table_number: int) -> int:
    """How many people seated at this table consent to recording."""
    roster = table_roster(session, assembly_id, table_number)
    return sum(1 for person in roster if person["recording_consent"])


def table_consent_state(
    session: Session, assembly: Assembly, table_number: int, round_id: str | None = None
) -> dict:
    roster = table_roster(session, assembly.id, table_number, round_id)
    return _state(
        assembly.participant_consent,
        len(roster),
        sum(1 for person in roster if person["recording_consent"]),
        sum(1 for person in roster if person["refused"]),
    )


def consent_by_table(session: Session, assembly: Assembly, round_id: str | None = None) -> dict[int, dict]:
    """Every table's registered / consenting / refusing counts in three
    queries — for the monitor, which asks for all tables at once every few
    seconds. With `round_id`, the seats of that session."""
    latest = latest_consents(session, assembly.id)
    counts: dict[int, dict] = {}
    for participant_id, number in _seats(session, assembly.id, round_id).items():
        entry = counts.setdefault(number, {"registered": 0, "consenting": 0, "refusing": 0})
        entry["registered"] += 1
        consent = latest.get(participant_id)
        if _stands(consent):
            entry["consenting"] += 1
        elif _refuses(consent):
            entry["refusing"] += 1
    return {
        number: _state(assembly.participant_consent, **entry) for number, entry in counts.items()
    }


def guard_recording(
    session: Session, assembly: Assembly, table_number: int, round_id: str | None = None
) -> None:
    """The rule behind 'required', enforced where recording starts."""
    if assembly.participant_consent != "required":
        return
    state = table_consent_state(session, assembly, table_number, round_id)
    if state["refusing"] > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "code": REFUSED_CODE,
                "message": "Someone seated at this table refused to be recorded — "
                           "mark them as moved to a table that is not recorded first",
            },
        )
    if state["consenting"] == 0:
        raise HTTPException(
            status_code=409,
            detail={
                "code": CONSENT_REQUIRED_CODE,
                "message": "Register at least one participant who consents to recording first",
            },
        )


def quotations_withheld_tables(session: Session, assembly: Assembly, round_id: str) -> set[int]:
    """Tables, in this session, where someone seated did not consent to being
    quoted (newest act, publication_consent false): no verbatim quotation
    from that table reaches the report. The whole table, not one voice:
    voices are not separated in the recording."""
    latest = latest_consents(session, assembly.id)
    withheld: set[int] = set()
    for participant_id, number in _seats(session, assembly.id, round_id).items():
        consent = latest.get(participant_id)
        if consent is not None and not consent.publication_consent:
            withheld.add(number)
    return withheld


def participant_at_table(
    session: Session, assembly: Assembly, participant_id: str, table_number: int
) -> Participant:
    """The person, if they sit at this table in the session being set up —
    a phone acts on its own table's people only (404 otherwise)."""
    participant = session.get(Participant, participant_id)
    if participant is None or participant.assembly_id != assembly.id:
        raise HTTPException(status_code=404, detail="Participant not found")
    seats = _seats(session, assembly.id, _current_round_id(session, assembly.id, table_number))
    if seats.get(participant.id) != table_number:
        raise HTTPException(status_code=404, detail="Participant not found at this table")
    return participant


def act(
    session: Session,
    assembly: Assembly,
    participant: Participant,
    *,
    notice_hash: str | None,
    notice_read: bool,
    recording: bool,
    transcription: bool,
    analysis: bool,
    publication: bool,
    method: str,
    recorder_session: RecorderSession | None = None,
    actor: str | None = None,
    notice: Notice | None = None,
) -> ParticipantConsent:
    """A further consent act by someone already registered: a change of mind
    after a refusal, or a withdrawal (every flag false). Append-only — the
    register keeps every act, and the newest one counts everywhere. Name and
    email are not touched. `notice_hash` None means the organizer acts on the
    person's word; a phone must carry the notice the person just read."""
    if assembly.closed_at is not None:
        raise HTTPException(status_code=409, detail="This assembly has been closed")
    if notice is None:
        notice = notice_for(assembly)
    if notice_hash is not None and notice_hash != notice.hash:
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
    table_number = participant.registered_table_number
    round_id = (
        _current_round_id(session, assembly.id, table_number) if table_number is not None else None
    )
    consent = ParticipantConsent(
        assembly_id=assembly.id,
        participant_id=participant.id,
        round_id=round_id,
        table_number=table_number,
        recorder_session_id=recorder_session.id if recorder_session else None,
        method=method,
        notice_hash=notice.hash,
        notice_version=notice.version,
        notice_language=notice.language,
        notice_read=notice_read,
        recording_consent=recording,
        transcription_consent=transcription,
        analysis_consent=analysis,
        publication_consent=publication,
        confirmed_at=utcnow(),
    )
    session.add(consent)
    session.flush()
    record_audit_event(
        session, "consent_changed", "participant", participant.id,
        actor=actor or (f"recorder-session:{recorder_session.id}" if recorder_session else None),
        data={
            "table": table_number,
            "round_id": round_id,
            "method": method,
            "notice_version": notice.version,
            "recording": recording,
            "transcription": transcription,
            "analysis": analysis,
            "publication": publication,
            "withdrawal": not (recording or transcription or analysis or publication),
        },
    )
    return consent


def unseat(session: Session, assembly: Assembly, participant: Participant, *, actor: str | None) -> None:
    """Marked as moved to another table (the room's procedure for a refusal:
    a table that is not recorded). The person leaves this table's roster for
    the sessions still to come; their consent acts stay as they are, and they
    can be seated elsewhere by name as a pre-registered person is."""
    if assembly.closed_at is not None:
        raise HTTPException(status_code=409, detail="This assembly has been closed")
    table_number = participant.registered_table_number
    open_round_ids = [
        r.id for r in assembly.rounds if r.status in ("NOT_STARTED", "ACTIVE")
    ]
    if open_round_ids:
        for assignment in session.execute(
            select(TableAssignment).where(
                TableAssignment.participant_id == participant.id,
                TableAssignment.round_id.in_(open_round_ids),
            )
        ).scalars():
            session.delete(assignment)
    participant.registered_table_number = None
    participant.registered_round_id = None
    participant.registered_session_id = None
    session.flush()
    record_audit_event(
        session, "participant_moved", "participant", participant.id, actor=actor,
        data={"from_table": table_number},
    )


#: a participant's page outlives the event: the report may come weeks later
PARTICIPANT_SESSION_LIFETIME = timedelta(days=180)


def registration_code(session: Session, token: str) -> tuple[RecorderInvite, Assembly]:
    """The REGISTER_PARTICIPANT code behind a token, or 401/409."""
    invite = invite_svc.find_by_token(session, token)
    if invite is None or invite.revoked_at is not None or invite_svc.is_expired(invite):
        raise HTTPException(status_code=401, detail="Invalid or expired registration code")
    # a table's code seats the person there; the assembly's pre-registration
    # link (no table) registers them to be seated at the door by name
    if invite.purpose != "REGISTER_PARTICIPANT":
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
        session, assembly, act,
        method="SELF_PHONE" if invite.table_number is not None else "PRE_REGISTRATION",
        table_number=invite.table_number, notice=notice,
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
    from citizens.services import validation as validation_svc

    rounds = [
        {
            "id": round_.id,
            "position": round_.position,
            "title": round_.title,
            "status": round_.status,
            # where this person sat (the seating, else where they registered)
            "table_number": validation_svc.table_for(session, participant, round_),
        }
        for round_ in sorted(assembly.rounds, key=lambda r: r.position)
    ]
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
        "rounds": rounds,
        # what this person already said about their table's summaries
        "validations": validation_svc.for_participant(session, participant.id),
        # where to go next: the first coming session with a seat for them
        "next_table": _next_table(rounds, participant),
        "contact": snapshot.consent_contact or organization_data().get("org_dpo", ""),
        "controller": snapshot.consent_controller or snapshot.organization_name,
    }


def _next_table(rounds: list[dict], participant: Participant) -> dict | None:
    """"Your next table: 4 · Green" — a seat worth announcing: in a coming
    session once the event is under way (a session has started or ended
    before it), or in any session where the seat differs from the table the
    person registered at (a remix moved them)."""
    under_way = False
    for round_ in rounds:
        if round_["status"] in ("ACTIVE", "ENDED", "PROCESSING", "READY_FOR_REVIEW"):
            under_way = True
        if round_["table_number"] is None:
            continue
        moved = round_["table_number"] != participant.registered_table_number
        if round_["status"] == "NOT_STARTED" and (under_way or moved):
            return _table_card(round_)
        if round_["status"] == "ACTIVE" and moved:
            return _table_card(round_)
    return None


def _table_card(round_: dict) -> dict:
    return {
        "round_position": round_["position"],
        "round_title": round_["title"],
        "table_number": round_["table_number"],
        "color_key": color_for(round_["table_number"]),
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


REGISTER_COLUMNS = (
    "label", "name", "email", "source", "table", "method", "notice_version", "notice_hash",
    "recording", "transcription", "analysis", "publication", "confirmed_at", "withdrawn_at",
)


def consent_register_rows(session: Session, assembly: Assembly) -> list[dict]:
    """One row per consent ACT — the register an authority or an auditor asks
    for, with a change of mind or a withdrawal as a further row under the same
    label. People from the organizer's list with no record are left out: they
    signed nothing here."""
    acts: dict[str, list[ParticipantConsent]] = {}
    for consent in session.execute(
        select(ParticipantConsent)
        .where(ParticipantConsent.assembly_id == assembly.id)
        .order_by(ParticipantConsent.confirmed_at.asc(), ParticipantConsent.created_at.asc())
    ).scalars():
        acts.setdefault(consent.participant_id, []).append(consent)
    rows = []
    for person in participants_with_consent(session, assembly):
        for record in acts.get(person["id"], []):
            consent = consent_dict(record)
            rows.append(
                {
                    "label": person["label"],
                    "name": person["name"],
                    "email": person["email"],
                    "source": person["source"],
                    "table": person["registered_table_number"] or "",
                    "method": consent["method"],
                    "notice_version": consent["notice_version"],
                    "notice_hash": consent["notice_hash"],
                    "recording": "yes" if consent["recording"] else "no",
                    "transcription": "yes" if consent["transcription"] else "no",
                    "analysis": "yes" if consent["analysis"] else "no",
                    "publication": "yes" if consent["publication"] else "no",
                    "confirmed_at": consent["confirmed_at"].isoformat() if consent["confirmed_at"] else "",
                    "withdrawn_at": consent["withdrawn_at"].isoformat() if consent["withdrawn_at"] else "",
                }
            )
    return rows


def consent_register_csv(session: Session, assembly: Assembly) -> str:
    import csv
    import io

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=REGISTER_COLUMNS)
    writer.writeheader()
    for row in consent_register_rows(session, assembly):
        writer.writerow(row)
    return out.getvalue()


def consent_register_pdf(session: Session, assembly: Assembly, organization_name: str = "") -> bytes:
    """A printable register: the assembly, one line per person, and the
    notice texts referenced, so the paper is complete on its own."""
    from citizens.services.qr_sheet import _SheetPDF
    from citizens.services.report_pdf import INK, MUTED

    rows = consent_register_rows(session, assembly)
    heading = " · ".join(part for part in (organization_name, assembly.name) if part)
    pdf = _SheetPDF(footer_text=f"{heading or assembly.name} — consent register")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font(pdf.family, "B", 16)
    pdf.set_text_color(*INK)
    pdf.cell(0, 10, "Consent register", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(pdf.family, "", 9)
    pdf.set_text_color(*MUTED)
    exported = utcnow().isoformat(timespec="minutes")
    pdf.cell(0, 5, f"{assembly.name} · {len(rows)} records · exported {exported}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for row in rows:
        pdf.set_font(pdf.family, "B", 10)
        pdf.set_text_color(*INK)
        verdict = "consented" if row["recording"] == "yes" else "did not consent"
        where = f" · Table {row['table']}" if row["table"] else ""
        title = f"{row['label']} · {row['name'] or '—'}{where} — {verdict}"
        pdf.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.family, "", 8.5)
        pdf.set_text_color(*MUTED)
        detail = (
            f"{row['method']} · {row['confirmed_at']} · notice {row['notice_version']} "
            f"({row['notice_hash'][:12]}…) · recording {row['recording']}, transcription "
            f"{row['transcription']}, analysis {row['analysis']}, quotations {row['publication']}"
        )
        if row["email"]:
            detail = f"{row['email']} · " + detail
        if row["withdrawn_at"]:
            detail += f" · withdrawn {row['withdrawn_at']}"
        pdf.multi_cell(0, 4.5, detail, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    if not rows:
        pdf.set_font(pdf.family, "", 11)
        pdf.cell(0, 8, "No consent has been recorded for this assembly.", new_x="LMARGIN", new_y="NEXT")
    # the texts people read, once per hash, so the register stands alone
    hashes = sorted({row["notice_hash"] for row in rows})
    for notice in session.execute(select(ConsentNotice).where(ConsentNotice.hash.in_(hashes))).scalars():
        pdf.add_page()
        pdf.set_font(pdf.family, "B", 12)
        pdf.set_text_color(*INK)
        pdf.cell(0, 8, f"Notice {notice.version} · {notice.language} · {notice.hash[:12]}…",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.family, "", 9.5)
        for paragraph in notice.text.split("\n"):
            pdf.multi_cell(0, 5, paragraph, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.5)
    return bytes(pdf.output())


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
