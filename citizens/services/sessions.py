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

from sqlalchemy.orm import Session

from citizens.db.models import Assembly, Round
from citizens.db.models.base import utcnow
from citizens.domain import schemas
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


def _container_name(question: str) -> str:
    """The sidebar's label: the question, or a neutral word when there is none."""
    text = " ".join(question.split())
    if not text:
        return "Session"
    return text if len(text) <= 200 else text[:197] + "…"


def _record_now_name(now: datetime) -> str:
    # ISO-like and language-neutral: the organizer may rename it afterwards
    return f"Recording {now:%Y-%m-%d %H:%M} UTC"
