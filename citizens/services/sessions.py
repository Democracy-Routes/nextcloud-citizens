# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone Sessions: the unit Citizens starts from in 0.7.

A Session is one question discussed at one or more tables, and the recordings
made there. An Assembly is the optional container that groups several Sessions
into an event. Nothing here asks the caller for an assembly.

How it is stored, and why that is not the product model
-------------------------------------------------------
The database still spells the hierarchy as Assembly → Round → Table, and
`assembly_id` is the key of every storage directory, ownership check, retention
sweep, device-audio purge, export and report. Making it nullable would touch
the recorder's critical path for the sake of a tidier schema. So a standalone
Session is a Round inside a container `Assembly(kind="session")`: created here,
named after the question, holding exactly one round, and shown by the organizer
UI as a Session — never as an assembly to configure. `Assembly.kind` is the
only thing that distinguishes the container from an organized event. A later
release may remodel the persistence once the Session abstraction has matured;
callers of this module should not notice.

"Record now" is the shortest path through this: an independent-mode Session
with one table, whose join link the caller opens on the phone in hand. In
independent mode a table records on its own schedule, so no facilitator has to
press Start for a round that nobody is orchestrating.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from citizens.db.models import Assembly, Recording, Round
from citizens.db.models.base import utcnow
from citizens.domain import schemas
from citizens.domain.tables import color_for
from citizens.logging_setup import get_logger
from citizens.services import assemblies as assemblies_svc
from citizens.services import invites as invite_svc
from citizens.services.audit import record_audit_event

log = get_logger(__name__)

#: `Assembly.kind` of the container behind a standalone Session.
SESSION_KIND = "session"
#: `Assembly.kind` of an event the user created as an assembly.
ASSEMBLY_KIND = "assembly"


@dataclass(frozen=True)
class StandaloneSession:
    container: Assembly
    round_: Round
    invites: list[schemas.InviteGenerated]

    @property
    def session_id(self) -> str:
        return self.round_.id

    @property
    def container_id(self) -> str:
        return self.container.id


def create_standalone_session(
    session: Session, user_id: str, data: schemas.SessionCreate
) -> StandaloneSession:
    """Create a Session that belongs to no assembly, with its tables and QR codes.

    The container is named after the question so the sidebar has something to
    show; plenary keeps the assembly rule of exactly one table.
    """
    table_count = 1 if data.recording_mode == "plenary" else data.table_count
    container = Assembly(
        kind=SESSION_KIND,
        name=_container_name(data.question),
        language=data.language,
        recording_mode=data.recording_mode,
        default_table_count=table_count,
        # a spontaneous Session offers registration but blocks nothing
        participant_consent="optional",
        created_by=user_id,
    )
    round_in = schemas.RoundIn(
        question=data.question,
        objective=data.objective,
        duration_minutes=data.duration_minutes,
    )
    round_ = assemblies_svc._build_round(round_in, 1, table_count)
    container.rounds.append(round_)
    session.add(container)
    session.flush()
    invites = invite_svc.generate_invites(session, container)
    record_audit_event(
        session, "session_created", "round", round_.id, actor=user_id,
        data={
            "container_id": container.id,
            "standalone": True,
            "recording_mode": data.recording_mode,
            "tables": table_count,
        },
    )
    log.info(
        "session_created",
        round_id=round_.id, container_id=container.id,
        recording_mode=data.recording_mode, tables=table_count,
    )
    return StandaloneSession(container=container, round_=round_, invites=invites)


def record_now(session: Session, user_id: str, language: str = "en") -> schemas.RecordNowOut:
    """The fastest path: a one-table independent Session and Table 1's join link.

    Independent mode because nobody is orchestrating: the phone that opens the
    link taps once and records. The question is left empty — there is nothing
    to ask yet — and the container is named after the moment instead.
    """
    data = schemas.SessionCreate(
        question="", recording_mode="independent", table_count=1, language=language
    )
    created = create_standalone_session(session, user_id, data)
    created.container.name = _record_now_name(utcnow())
    [card] = created.invites
    return schemas.RecordNowOut(
        session_id=created.session_id,
        container_id=created.container_id,
        table_number=card.table_number,
        recorder_url=card.url,
    )


def created_payload(created: StandaloneSession) -> schemas.SessionCreated:
    return schemas.SessionCreated(
        session_id=created.session_id,
        container_id=created.container_id,
        question=created.round_.question,
        objective=created.round_.objective,
        recording_mode=created.container.recording_mode,
        table_count=created.container.default_table_count,
        invites=created.invites,
    )


def promote_to_assembly(
    session: Session, round_: Round, name: str, actor: str | None = None
) -> schemas.PromotedOut:
    """A standalone Session grows into an Assembly: the moment a second session
    is wanted, the container stops being hidden and becomes the event.

    Nothing else changes — the round, its tables, invites, recordings, reports
    and files already live in the container — so choosing "Start a Session"
    first is never a mistake. Idempotent: an assembly stays as it is.
    """
    container = round_.assembly
    if container.kind != SESSION_KIND:
        return schemas.PromotedOut(container_id=container.id, kind=container.kind, name=container.name)
    container.kind = ASSEMBLY_KIND
    container.name = " ".join(name.split())[:200] or container.name
    session.flush()
    record_audit_event(
        session, "session_promoted", "assembly", container.id, actor=actor,
        data={"round_id": round_.id, "name": container.name},
    )
    log.info("session_promoted", container_id=container.id, round_id=round_.id)
    return schemas.PromotedOut(container_id=container.id, kind=container.kind, name=container.name)


def session_detail(session: Session, round_: Round) -> schemas.SessionOut:
    """A round in product vocabulary (domain/vocabulary.py)."""
    recording_count = session.execute(
        select(func.count()).select_from(Recording).where(Recording.round_id == round_.id)
    ).scalar_one()
    container = round_.assembly
    return schemas.SessionOut(
        session_id=round_.id,
        container_id=container.id,
        container_name=container.name,
        standalone=container.kind == SESSION_KIND,
        position=round_.position,
        title=round_.title,
        question=round_.question,
        objective=round_.objective,
        duration_minutes=round_.duration_minutes,
        status=round_.status,
        recording_mode=container.recording_mode,
        language=container.language,
        started_at=round_.started_at,
        ended_at=round_.ended_at,
        tables=[
            schemas.SessionTableOut(
                id=table.id, number=table.number, color_key=table.color_key or color_for(table.number)
            )
            for table in round_.tables
        ],
        recording_count=recording_count,
    )


def list_sessions(session: Session, user_id: str) -> list[schemas.SessionOut]:
    """Every Session the user owns, standalone ones and those inside assemblies,
    newest container first then by position."""
    rounds = session.execute(
        select(Round)
        .join(Assembly, Assembly.id == Round.assembly_id)
        .where(Assembly.created_by == user_id)
        .order_by(Assembly.created_at.desc(), Round.position)
    ).scalars()
    return [session_detail(session, round_) for round_ in rounds]


def _container_name(question: str) -> str:
    """The sidebar's label: the question, or a neutral word when there is none."""
    text = " ".join(question.split())
    if not text:
        return "Session"
    return text if len(text) <= 200 else text[:197] + "…"


def _record_now_name(now: datetime) -> str:
    # ISO-like and language-neutral: the organizer may rename it afterwards
    return f"Recording {now:%Y-%m-%d %H:%M} UTC"
