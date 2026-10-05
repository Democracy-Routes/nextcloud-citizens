# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tables as the room sees them: numbered, coloured, and addable while it runs.

A `Table` row belongs to one round, so an assembly of three rounds and ten
tables holds thirty rows — the *table* the room knows is the number, which is
the same in every round, is printed on the QR sheet, and is what a phone
carries. This module works at that level: the set of numbers an assembly has,
and adding the next one to every round at once.

Until 0.7 the count was fixed when the assembly was created and
`default_table_count` was the source of truth for "how many tables are
expected". Now that a table can appear mid-event, the rows are the truth and
`default_table_count` only seeds the rounds added later.
"""

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from citizens.db.models import Assembly, Table
from citizens.domain import schemas
from citizens.domain.tables import color_for
from citizens.logging_setup import get_logger
from citizens.services import invites as invite_svc
from citizens.services.audit import record_audit_event

log = get_logger(__name__)


def table_numbers(assembly: Assembly) -> list[int]:
    """Every table number the assembly has, across all its rounds, ascending.

    Falls back to `default_table_count` for an assembly that has no rounds yet
    (and so no rows), which is what the QR sheet does too.
    """
    numbers = {table.number for round_ in assembly.rounds for table in round_.tables}
    if not numbers:
        numbers = set(range(1, assembly.default_table_count + 1))
    return sorted(numbers)


def add_table(session: Session, assembly: Assembly, actor: str | None = None) -> schemas.TableAdded:
    """Add the next table to every round of the assembly and issue its QR code.

    Numbers are allocated max+1 under SQLite's single writer lock — the session
    took it with its first statement (`BEGIN IMMEDIATE`), so two organizers
    adding at once are serialised and cannot pick the same number. The unique
    constraint on (round, number) is the backstop should that ever change.
    """
    if assembly.closed_at is not None:
        raise HTTPException(status_code=409, detail="This assembly has been closed")
    if assembly.recording_mode == "plenary":
        raise HTTPException(
            status_code=409, detail="A plenary room is one table; add phones to it instead"
        )
    number = max(table_numbers(assembly), default=0) + 1
    color = color_for(number)
    for round_ in assembly.rounds:
        round_.tables.append(Table(number=number, color_key=color))
    # rounds added later are built from this count, so they get the table too
    assembly.default_table_count = max(assembly.default_table_count, number)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Another table was being added at the same moment; try again"
        ) from None
    card = invite_svc.issue_invite(session, assembly, number)
    record_audit_event(
        session, "table_added", "assembly", assembly.id, actor=actor,
        data={"number": number, "color_key": color, "rounds": len(assembly.rounds)},
    )
    log.info("table_added", assembly_id=assembly.id, number=number, color_key=color)
    return schemas.TableAdded(number=number, color_key=color, invite=card)
