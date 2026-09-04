# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assembly-core domain operations."""

import csv
import io
import random

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from citizens.db.models import Assembly, Participant, Round, Table, TableAssignment
from citizens.domain import schemas


def get_owned_assembly(session: Session, assembly_id: str, user_id: str) -> Assembly:
    """404 for both 'missing' and 'not yours' so existence is not leaked."""
    assembly = session.get(Assembly, assembly_id)
    if assembly is None or assembly.created_by != user_id:
        raise HTTPException(status_code=404, detail="Assembly not found")
    return assembly


def get_owned_round(session: Session, round_id: str, user_id: str) -> Round:
    round_ = session.get(Round, round_id)
    if round_ is None or round_.assembly.created_by != user_id:
        raise HTTPException(status_code=404, detail="Round not found")
    return round_


def create_assembly(session: Session, user_id: str, data: schemas.AssemblyCreate) -> Assembly:
    assembly = Assembly(
        name=data.name,
        description=data.description,
        language=data.language,
        scheduled_at=data.scheduled_at,
        recording_mode=data.recording_mode,
        expected_participants=data.expected_participants,
        default_table_count=data.default_table_count,
        analysis_instructions=data.analysis_instructions,
        auto_purge_device_audio=data.auto_purge_device_audio,
        redact_names=data.redact_names,
        created_by=user_id,
    )
    for position, round_in in enumerate(data.rounds, start=1):
        assembly.rounds.append(_build_round(round_in, position, data.default_table_count))
    session.add(assembly)
    session.flush()
    return assembly


def _build_round(round_in: schemas.RoundIn, position: int, table_count: int) -> Round:
    round_ = Round(
        position=position,
        title=round_in.title,
        question=round_in.question,
        duration_minutes=round_in.duration_minutes,
    )
    for number in range(1, table_count + 1):
        round_.tables.append(Table(number=number))
    return round_


def add_round(session: Session, assembly: Assembly, round_in: schemas.RoundIn) -> Round:
    position = max((r.position for r in assembly.rounds), default=0) + 1
    round_ = _build_round(round_in, position, assembly.default_table_count)
    assembly.rounds.append(round_)
    session.flush()
    return round_


def update_round(session: Session, round_: Round, data: schemas.RoundUpdate) -> Round:
    if data.title is not None:
        round_.title = data.title
    if data.question is not None:
        round_.question = data.question
    if data.duration_minutes is not None:
        round_.duration_minutes = data.duration_minutes
    if data.position is not None and data.position != round_.position:
        _reorder_round(round_, data.position)
    session.flush()
    return round_


def _reorder_round(round_: Round, new_position: int) -> None:
    rounds = sorted(round_.assembly.rounds, key=lambda r: r.position)
    rounds.remove(round_)
    rounds.insert(min(new_position, len(rounds) + 1) - 1, round_)
    for index, item in enumerate(rounds, start=1):
        item.position = index


def delete_round(session: Session, round_: Round) -> None:
    assembly = round_.assembly
    assembly.rounds.remove(round_)
    for index, item in enumerate(sorted(assembly.rounds, key=lambda r: r.position), start=1):
        item.position = index
    session.flush()


def add_participants(
    session: Session, assembly: Assembly, participants: list[schemas.ParticipantIn]
) -> list[Participant]:
    existing_labels = {p.label for p in assembly.participants}
    created: list[Participant] = []
    for item in participants:
        if item.label in existing_labels:
            raise HTTPException(status_code=409, detail=f"Duplicate participant label: {item.label}")
        existing_labels.add(item.label)
        participant = Participant(
            label=item.label, name=item.name, email=item.email, notes=item.notes
        )
        assembly.participants.append(participant)
        created.append(participant)
    session.flush()
    return created


def parse_participants_csv(csv_text: str) -> list[schemas.ParticipantIn]:
    """CSV with a `label,name,email` header (brief §11); name/email optional."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if reader.fieldnames is None or "label" not in [f.strip().lower() for f in reader.fieldnames]:
        raise HTTPException(status_code=422, detail="CSV must have a header containing 'label'")
    participants = []
    for row in reader:
        normalized = {(key or "").strip().lower(): (value or "").strip() for key, value in row.items()}
        if not normalized.get("label"):
            continue
        participants.append(
            schemas.ParticipantIn(
                label=normalized["label"],
                name=normalized.get("name", ""),
                email=normalized.get("email", ""),
                notes=normalized.get("notes", ""),
            )
        )
    if not participants:
        raise HTTPException(status_code=422, detail="CSV contains no participants")
    return participants


def randomize_assignments(session: Session, round_: Round) -> None:
    """Shuffle all assembly participants and deal them round-robin to tables."""
    if not round_.tables:
        raise HTTPException(status_code=422, detail="Round has no tables")
    participants = list(round_.assembly.participants)
    random.shuffle(participants)
    _replace_assignments(
        session,
        round_,
        {
            participant.id: round_.tables[index % len(round_.tables)].id
            for index, participant in enumerate(participants)
        },
    )


def copy_previous_assignments(session: Session, round_: Round) -> None:
    previous = next(
        (r for r in sorted(round_.assembly.rounds, key=lambda r: r.position, reverse=True)
         if r.position < round_.position),
        None,
    )
    if previous is None:
        raise HTTPException(status_code=422, detail="No previous round to copy from")
    tables_by_number = {t.number: t for t in round_.tables}
    mapping: dict[str, str] = {}
    for assignment in _round_assignments(session, previous.id):
        target = tables_by_number.get(assignment.table.number)
        if target is not None:
            mapping[assignment.participant_id] = target.id
    _replace_assignments(session, round_, mapping)


def move_assignment(session: Session, round_: Round, participant_id: str, to_table_id: str) -> None:
    if to_table_id not in {t.id for t in round_.tables}:
        raise HTTPException(status_code=422, detail="Table does not belong to this round")
    assignment = session.execute(
        select(TableAssignment).where(
            TableAssignment.round_id == round_.id,
            TableAssignment.participant_id == participant_id,
        )
    ).scalar_one_or_none()
    if assignment is None:
        session.add(
            TableAssignment(round_id=round_.id, table_id=to_table_id, participant_id=participant_id)
        )
    else:
        assignment.table_id = to_table_id
    session.flush()


def _replace_assignments(session: Session, round_: Round, participant_to_table: dict[str, str]) -> None:
    for assignment in _round_assignments(session, round_.id):
        session.delete(assignment)
    session.flush()
    for participant_id, table_id in participant_to_table.items():
        session.add(
            TableAssignment(round_id=round_.id, table_id=table_id, participant_id=participant_id)
        )
    session.flush()


def _round_assignments(session: Session, round_id: str) -> list[TableAssignment]:
    return list(
        session.execute(
            select(TableAssignment)
            .where(TableAssignment.round_id == round_id)
            .options(selectinload(TableAssignment.table), selectinload(TableAssignment.participant))
        ).scalars()
    )


def tables_with_participants(session: Session, round_: Round) -> list[schemas.TableOut]:
    assignments_by_table: dict[str, list[Participant]] = {}
    for assignment in _round_assignments(session, round_.id):
        assignments_by_table.setdefault(assignment.table_id, []).append(assignment.participant)
    return [
        schemas.TableOut(
            id=table.id,
            number=table.number,
            label=table.label,
            status=table.status,
            participants=[
                schemas.ParticipantOut.model_validate(p)
                for p in sorted(assignments_by_table.get(table.id, []), key=lambda p: p.label)
            ],
        )
        for table in round_.tables
    ]
