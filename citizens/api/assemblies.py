# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer API: assemblies, rounds, participants, table assignments."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import Assembly, HelpRequest, Participant, RecorderSession, Recording
from citizens.db.session import get_db, get_read_db
from citizens.domain import schemas
from citizens.security.identity import CurrentUser
from citizens.services import assemblies as svc
from citizens.services import consent as consent_svc
from citizens.services import help as help_svc
from citizens.services import invites as invite_svc
from citizens.services import messages as messages_svc
from citizens.services import rounds as rounds_svc
from citizens.services import tables as tables_svc
from citizens.services.audit import record_audit_event
from citizens.storage.paths import purge_assembly_storage

router = APIRouter()

DB = Annotated[Session, Depends(get_db)]
# round_monitor is polled every few seconds by every open organizer tab for the
# whole length of an event. Taking SQLite's writer slot for it competes with
# the phones' chunk uploads for no reason: it only reads.
ReadDB = Annotated[Session, Depends(get_read_db)]


@router.get("/assemblies", response_model=list[schemas.AssemblyOut])
def list_assemblies(user: CurrentUser, session: ReadDB):
    return list(
        session.execute(
            select(Assembly).where(Assembly.created_by == user).order_by(Assembly.created_at.desc())
        ).scalars()
    )


@router.post("/assemblies", response_model=schemas.AssemblyCreated, status_code=201)
def create_assembly(data: schemas.AssemblyCreate, user: CurrentUser, session: DB):
    assembly = svc.create_assembly(session, user, data)
    # QR codes exist by default; the raw links live only in this response
    invites = invite_svc.generate_invites(session, assembly)
    record_audit_event(
        session, "assembly_created", "assembly", assembly.id, actor=user,
        data={"invites": len(invites)},
    )
    detail = _detail(session, assembly)
    return schemas.AssemblyCreated(**detail.model_dump(), invites=invites)


@router.get("/assemblies/{assembly_id}", response_model=schemas.AssemblyDetail)
def get_assembly(assembly_id: str, user: CurrentUser, session: ReadDB):
    return _detail(session, svc.get_owned_assembly(session, assembly_id, user))


@router.put("/assemblies/{assembly_id}", response_model=schemas.AssemblyDetail)
def update_assembly(assembly_id: str, data: schemas.AssemblyUpdate, user: CurrentUser, session: DB):
    assembly = svc.get_owned_assembly(session, assembly_id, user)
    fields = data.model_dump(exclude_unset=True)
    # Language and recording mode decide how audio is transcribed and whether a
    # phone may record without the facilitator; changing either once any audio
    # exists would leave one assembly with transcripts in two languages, or
    # flip recording rules mid-event. The client hides them once recording
    # starts, but a stale second tab or a direct PUT could still send them, so
    # the rule lives here too. Name, description, instructions, toggles stay
    # editable throughout.
    locked = {"language", "recording_mode"}
    changed = {
        field
        for field in locked & fields.keys()
        if fields[field] != getattr(assembly, field)
    }
    if changed and _assembly_has_recordings(session, assembly_id):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot change {', '.join(sorted(changed))} once recording has begun.",
        )
    for field, value in fields.items():
        setattr(assembly, field, value)
    session.flush()
    return _detail(session, assembly)


def _assembly_has_recordings(session: Session, assembly_id: str) -> bool:
    return (
        session.execute(
            select(Recording.id).where(Recording.assembly_id == assembly_id).limit(1)
        ).first()
        is not None
    )


@router.delete("/assemblies/{assembly_id}", status_code=204)
def delete_assembly(assembly_id: str, user: CurrentUser, session: DB):
    assembly = svc.get_owned_assembly(session, assembly_id, user)
    record_audit_event(session, "assembly_deleted", "assembly", assembly.id, actor=user,
                       data={"name": assembly.name})
    # collected before the cascade removes the rows: the phones' diagnostic
    # logs are keyed by session id and live outside the per-assembly tree
    device_sessions = [
        row
        for row in session.execute(
            select(RecorderSession.id).where(RecorderSession.assembly_id == assembly_id)
        ).scalars()
    ]
    session.delete(assembly)
    session.flush()
    # deleting the session deletes its audio too — chunks, canonical files,
    # transcripts, exports and device logs all leave the disk with the rows
    purge_assembly_storage(
        get_settings().app_persistent_storage, assembly_id, device_sessions
    )


@router.post("/assemblies/{assembly_id}/rounds", response_model=schemas.RoundOut, status_code=201)
def add_round(assembly_id: str, data: schemas.RoundIn, user: CurrentUser, session: DB):
    assembly = svc.get_owned_assembly(session, assembly_id, user)
    return svc.add_round(session, assembly, data)


@router.put("/rounds/{round_id}", response_model=schemas.RoundOut)
def update_round(round_id: str, data: schemas.RoundUpdate, user: CurrentUser, session: DB):
    round_ = svc.get_owned_round(session, round_id, user)
    return svc.update_round(session, round_, data)


@router.delete("/rounds/{round_id}", status_code=204)
def delete_round(round_id: str, user: CurrentUser, session: DB):
    round_ = svc.get_owned_round(session, round_id, user)
    svc.delete_round(session, round_)


@router.post("/rounds/{round_id}/start", response_model=schemas.RoundOut)
def start_round(round_id: str, user: CurrentUser, session: DB):
    round_ = svc.get_owned_round(session, round_id, user)
    rounds_svc.start_round(session, round_)
    record_audit_event(session, "round_started", "round", round_.id, actor=user)
    return round_


@router.post("/rounds/{round_id}/end", response_model=schemas.RoundOut)
def end_round(round_id: str, user: CurrentUser, session: DB):
    round_ = svc.get_owned_round(session, round_id, user)
    rounds_svc.end_round(session, round_)
    record_audit_event(session, "round_ended", "round", round_.id, actor=user)
    return round_


@router.get("/rounds/{round_id}/monitor")
def round_monitor(round_id: str, user: CurrentUser, session: ReadDB):
    round_ = svc.get_owned_round(session, round_id, user)
    return rounds_svc.round_monitor(session, round_)


@router.post("/rounds/{round_id}/messages", response_model=schemas.MessageOut, status_code=201)
def send_message(round_id: str, data: schemas.MessageIn, user: CurrentUser, session: DB):
    """Say something to every table of this session, or to one: "5 minutes
    left", "wrap up", a prompt. Rides the phones' status poll; the phones
    report receipt, which GET below shows as delivered / not yet."""
    round_ = svc.get_owned_round(session, round_id, user)
    message = messages_svc.post_message(
        session, round_, actor=user, kind=data.kind, text=data.text, minutes=data.minutes,
        target_table_number=data.target_table_number, sound=data.sound,
    )
    return messages_svc.list_with_delivery(session, round_, limit=1)[0] | {"id": message.id}


@router.get("/rounds/{round_id}/messages", response_model=list[schemas.MessageOut])
def list_messages(round_id: str, user: CurrentUser, session: ReadDB):
    round_ = svc.get_owned_round(session, round_id, user)
    return messages_svc.list_with_delivery(session, round_)


@router.post("/help-requests/{request_id}/acknowledge")
def acknowledge_help(request_id: str, user: CurrentUser, session: DB):
    """The organizer has seen a table's hand. The table's phone reads this
    on its next status poll; the row leaves the Live tab's attention list."""
    request = session.get(HelpRequest, request_id)
    if request is None or request.assembly.created_by != user:
        raise HTTPException(status_code=404, detail="Help request not found")
    return help_svc.as_dict(help_svc.acknowledge(session, request, user))


@router.get("/rounds/{round_id}/readiness")
def round_readiness(round_id: str, user: CurrentUser, session: ReadDB):
    """Can each table record? READY / NEEDS_ATTENTION / BLOCKED with reason
    codes — the monitor's judgement without its detail, for an exception-first
    view or an organizer's autopilot."""
    round_ = svc.get_owned_round(session, round_id, user)
    monitor = rounds_svc.round_monitor(session, round_)
    return {
        "round_id": round_.id,
        "status": round_.status,
        **monitor["readiness"],
        "tables": [
            {
                "table_id": table["table_id"],
                "number": table["number"],
                "color_key": table["color_key"],
                "recorders": len(table["recorders"]),
                "live_source_slot": table["live_source_slot"],
                **table["readiness"],
            }
            for table in monitor["tables"]
        ],
    }


@router.get("/assemblies/{assembly_id}/participants", response_model=list[schemas.ParticipantOut])
def list_participants(assembly_id: str, user: CurrentUser, session: ReadDB):
    assembly = svc.get_owned_assembly(session, assembly_id, user)
    return consent_svc.participants_with_consent(session, assembly)


@router.post("/assemblies/{assembly_id}/registration-link")
def registration_link(assembly_id: str, user: CurrentUser, session: DB):
    """The assembly's pre-registration link (made on first ask, then the same
    one): people register and consent at home, and are seated at the door
    by name on the table's phone."""
    assembly = svc.get_owned_assembly(session, assembly_id, user)
    card = invite_svc.registration_link(session, assembly)
    record_audit_event(session, "registration_link_issued", "assembly", assembly.id, actor=user)
    return {**card, "registered": _pre_registered(session, assembly)}


@router.get("/assemblies/{assembly_id}/registration-link")
def get_registration_link(assembly_id: str, user: CurrentUser, session: ReadDB):
    assembly = svc.get_owned_assembly(session, assembly_id, user)
    card = invite_svc.registration_link(session, assembly, create=False)
    return {**(card or {"url": None, "qr_svg": None, "expires_at": None}),
            "registered": _pre_registered(session, assembly)}


def _pre_registered(session: Session, assembly: Assembly) -> dict:
    """How many registered ahead, and how many of them have been seated."""
    people = [p for p in assembly.participants if p.source == "PRE_REGISTRATION"]
    return {
        "total": len(people),
        "seated": sum(1 for p in people if p.registered_table_number is not None),
    }


@router.get("/assemblies/{assembly_id}/consent-register.csv")
def consent_register_csv(assembly_id: str, user: CurrentUser, session: ReadDB):
    """The consent register as an auditor asks for it: one row per person
    with what they accepted, against which notice, when, by which method."""
    from fastapi.responses import Response

    from citizens.api.downloads import download_headers

    assembly = svc.get_owned_assembly(session, assembly_id, user)
    body = consent_svc.consent_register_csv(session, assembly)
    filename = f"{assembly.name[:40].replace(' ', '-')}-consent-register.csv"
    return Response(body, media_type="text/csv; charset=utf-8", headers=download_headers(filename))


@router.get("/assemblies/{assembly_id}/consent-register.pdf")
def consent_register_pdf(assembly_id: str, user: CurrentUser, session: ReadDB):
    from fastapi.responses import Response

    from citizens.api.downloads import download_headers
    from citizens.services.branding import organization_name

    assembly = svc.get_owned_assembly(session, assembly_id, user)
    body = consent_svc.consent_register_pdf(session, assembly, organization_name())
    filename = f"{assembly.name[:40].replace(' ', '-')}-consent-register.pdf"
    return Response(body, media_type="application/pdf", headers=download_headers(filename))


@router.post(
    "/assemblies/{assembly_id}/participants",
    response_model=list[schemas.ParticipantOut],
    status_code=201,
)
def add_participants(assembly_id: str, data: schemas.ParticipantsBulkIn, user: CurrentUser, session: DB):
    assembly = svc.get_owned_assembly(session, assembly_id, user)
    return svc.add_participants(session, assembly, data.participants)


@router.post(
    "/assemblies/{assembly_id}/participants/import-csv",
    response_model=list[schemas.ParticipantOut],
    status_code=201,
)
def import_participants_csv(assembly_id: str, data: schemas.CsvImportIn, user: CurrentUser, session: DB):
    assembly = svc.get_owned_assembly(session, assembly_id, user)
    return svc.add_participants(session, assembly, svc.parse_participants_csv(data.csv))


@router.delete("/participants/{participant_id}", status_code=204)
def delete_participant(participant_id: str, user: CurrentUser, session: DB):
    participant = session.get(Participant, participant_id)
    if participant is not None and participant.assembly.created_by == user:
        session.delete(participant)


@router.get("/rounds/{round_id}/tables", response_model=list[schemas.TableOut])
def round_tables(round_id: str, user: CurrentUser, session: ReadDB):
    round_ = svc.get_owned_round(session, round_id, user)
    return svc.tables_with_participants(session, round_)


@router.post("/assemblies/{assembly_id}/tables", response_model=schemas.TableAdded, status_code=201)
def add_table(assembly_id: str, user: CurrentUser, session: DB):
    """Add the next table — to every round at once — while the event runs.

    The QR code for the new table is in this response only; the codes already
    on the wall stay valid."""
    assembly = svc.get_owned_assembly(session, assembly_id, user)
    return tables_svc.add_table(session, assembly, actor=user)


@router.post("/rounds/{round_id}/assignments/randomize", response_model=list[schemas.TableOut])
def randomize(round_id: str, user: CurrentUser, session: DB):
    round_ = svc.get_owned_round(session, round_id, user)
    svc.randomize_assignments(session, round_)
    return svc.tables_with_participants(session, round_)


@router.post("/rounds/{round_id}/assignments/copy-previous", response_model=list[schemas.TableOut])
def copy_previous(round_id: str, user: CurrentUser, session: DB):
    round_ = svc.get_owned_round(session, round_id, user)
    svc.copy_previous_assignments(session, round_)
    return svc.tables_with_participants(session, round_)


@router.post("/rounds/{round_id}/assignments/move", response_model=list[schemas.TableOut])
def move(round_id: str, data: schemas.AssignmentMove, user: CurrentUser, session: DB):
    round_ = svc.get_owned_round(session, round_id, user)
    svc.move_assignment(session, round_, data.participant_id, data.to_table_id)
    return svc.tables_with_participants(session, round_)


def _detail(session: Session, assembly: Assembly) -> schemas.AssemblyDetail:
    count = session.execute(
        select(func.count()).select_from(Participant).where(Participant.assembly_id == assembly.id)
    ).scalar_one()
    detail = schemas.AssemblyDetail.model_validate(assembly, from_attributes=True)
    detail.participant_count = count
    recordings = dict(
        session.execute(
            select(Recording.round_id, func.count())
            .where(Recording.assembly_id == assembly.id)
            .group_by(Recording.round_id)
        ).all()
    )
    for round_out in detail.rounds:
        round_out.recording_count = recordings.get(round_out.id, 0)
    return detail
