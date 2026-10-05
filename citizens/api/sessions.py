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

from citizens.db.session import get_db
from citizens.domain import schemas
from citizens.security.identity import CurrentUser
from citizens.services import sessions as sessions_svc

router = APIRouter()

DB = Annotated[Session, Depends(get_db)]


@router.post("/sessions", response_model=schemas.SessionCreated, status_code=201)
def create_session(data: schemas.SessionCreate, user: CurrentUser, session: DB):
    """Start a Session: question, optional objective, tables — no assembly."""
    created = sessions_svc.create_standalone_session(session, user, data)
    return sessions_svc.created_payload(created)


@router.post("/sessions/record-now", response_model=schemas.RecordNowOut, status_code=201)
def record_now(data: schemas.RecordNowIn, user: CurrentUser, session: DB):
    """Record now: a one-table Session and the link that makes this phone its recorder."""
    return sessions_svc.record_now(session, user, language=data.language)
