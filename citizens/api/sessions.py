# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer API: Sessions that stand on their own.

The product vocabulary is Session; the rows behind it are a Round inside a
container assembly (services/sessions.py). A created Session is addressed by
its `session_id` on every existing `/rounds/{id}` route, and its organizer
screens are reached through `container_id` on the `/assemblies/{id}` routes —
the UI shows that container as a Session.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from citizens.db.session import get_db, get_read_db
from citizens.domain import schemas
from citizens.security.identity import CurrentUser
from citizens.services import sessions as sessions_svc
from citizens.services.assemblies import get_owned_round

router = APIRouter()

DB = Annotated[Session, Depends(get_db)]
ReadDB = Annotated[Session, Depends(get_read_db)]


@router.get("/sessions", response_model=list[schemas.SessionOut])
def list_sessions(user: CurrentUser, session: ReadDB):
    """Every Session the user owns — standalone ones and those inside assemblies —
    in product vocabulary (domain/vocabulary.py)."""
    return sessions_svc.list_sessions(session, user)


@router.post("/sessions/{session_id}/promote", response_model=schemas.PromotedOut)
def promote_session(session_id: str, data: schemas.PromoteSessionIn, user: CurrentUser, session: DB):
    """A standalone Session becomes an Assembly (an event of several sessions),
    keeping everything it already has. Idempotent for an assembly."""
    round_ = get_owned_round(session, session_id, user)
    return sessions_svc.promote_to_assembly(session, round_, data.name, actor=user)


@router.get("/sessions/{session_id}", response_model=schemas.SessionOut)
def get_session(session_id: str, user: CurrentUser, session: ReadDB):
    """A Session by its id — the same id every `/rounds/{id}` route accepts."""
    return sessions_svc.session_detail(session, get_owned_round(session, session_id, user))


@router.post("/sessions", response_model=schemas.SessionCreated, status_code=201)
def create_session(data: schemas.SessionCreate, user: CurrentUser, session: DB):
    """Start a Session: question, optional objective, tables — no assembly."""
    created = sessions_svc.create_standalone_session(session, user, data)
    return sessions_svc.created_payload(created)


@router.post("/sessions/record-now", response_model=schemas.RecordNowOut, status_code=201)
def record_now(data: schemas.RecordNowIn, user: CurrentUser, session: DB):
    """Record now: a one-table Session and the link that makes this phone its recorder."""
    return sessions_svc.record_now(session, user, language=data.language)
